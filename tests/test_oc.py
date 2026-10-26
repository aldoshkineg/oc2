#!/usr/bin/env python3
"""Tests for ./oc: unit (in-process) + e2e (subprocess, OC_DRY_RUN).

Podman is not required: no test starts a container.
Run:  make test      (or: python3 -m unittest discover -s tests)
"""

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
OC = REPO / "oc"

# The daynews example profile with the project directory {home}/src/daynews
DAYNEWS_TOML = textwrap.dedent("""
    [daynews]
    state = "oc2"
    paths = ["{home}/src/daynews"]
    mount = [
      "{home}/.local/state/daynews",
      "{home}/.local/share/newsboat/cache.db",
      "{home}/.config/newsboat/urls",
    ]
""")

# A persistent project: the named container keeps the layer between runs
PERSISTENT_TOML = textwrap.dedent("""
    [daynews]
    state = "oc"
    persistent = true
    paths = ["{home}/src/daynews"]
    mount = [
      "{home}/.local/state/daynews",
    ]
""")


def load_oc():
    loader = importlib.machinery.SourceFileLoader("oc_mod", str(OC))
    spec = importlib.util.spec_from_loader("oc_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


oc = load_oc()


class Base(unittest.TestCase):
    """Isolated $HOME + cwd + environment for each test."""

    def setUp(self):
        self.old_cwd = os.getcwd()
        self.old_env = dict(os.environ)
        self.tmp = Path(tempfile.mkdtemp(prefix="oc-test-"))
        self.home = self.tmp / "home"
        (self.home / ".config").mkdir(parents=True)
        os.environ["HOME"] = str(self.home)
        os.environ.pop("OC_IMAGE", None)
        os.environ.pop("OC_PROFILES", None)
        os.environ.pop("OC_DATA", None)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def daynews_fixture(self):
        """Project directory + the daynews mount sources."""
        (self.home / "src/daynews").mkdir(parents=True)
        (self.home / ".local/state/daynews").mkdir(parents=True)
        nb = self.home / ".local/share/newsboat"
        nb.mkdir(parents=True)
        (nb / "cache.db").write_text("x")
        cfg = self.home / ".config/newsboat"
        cfg.mkdir(parents=True)
        (cfg / "urls").write_text("x")
        return self.home / "src/daynews"

    def set_profiles(self, text):
        p = self.tmp / "profiles.toml"
        p.write_text(text.format(home=self.home))
        os.environ["OC_PROFILES"] = str(p)
        return p

    def oc_run(self, args, cwd=None, env=None):
        e = dict(os.environ)
        e.setdefault("OC_IMAGE", "x:1")
        e.setdefault("OC_DRY_RUN", "1")
        e.setdefault("OC_PROFILES", str(self.tmp / "profiles.toml"))
        if env:
            e.update(env)
        return subprocess.run(
            [sys.executable, str(OC), *args],
            capture_output=True,
            text=True,
            env=e,
            cwd=str(cwd or self.tmp),
        )


class Mirror(Base):
    def test_xdg_mirror(self):
        self.assertEqual(
            oc.mirror(Path("~/.local/state/daynews")), "/data/state/daynews"
        )
        self.assertEqual(
            oc.mirror(Path("~/.local/share/newsboat/cache.db")),
            "/data/data/newsboat/cache.db",
        )
        self.assertEqual(
            oc.mirror(Path("~/.config/newsboat/urls")), "/data/cfg/newsboat/urls"
        )
        self.assertEqual(oc.mirror(Path("~/.cache/misc")), "/data/cache/misc")

    def test_outside_home(self):
        self.assertEqual(oc.mirror(Path("/opt/daynotes")), "/mnt/daynotes")

    def test_vol(self):
        self.assertEqual(oc.Bind("/a", "/b", "ro").vol(), "/a:/b:ro")
        self.assertEqual(oc.Bind("/a", "/b").vol(), "/a:/b")


class ParseEntry(Base):
    def test_forms(self):
        p = self.tmp / "f1"
        p.write_text("x")
        b = oc.parse_entry(str(p), "t")
        self.assertEqual(b.dst, oc.mirror(p))
        b = oc.parse_entry(f"{p}:/data/x", "t")
        self.assertEqual((b.src, b.dst), (str(p), "/data/x"))
        b = oc.parse_entry(f"{p}:/data/x:ro", "t")
        self.assertEqual((b.dst, b.opts), ("/data/x", "ro"))

    def test_bad_spec(self):
        with self.assertRaises(SystemExit) as cm:
            oc.parse_entry("a:b:c:d", "t")
        self.assertIn("oc:", str(cm.exception))

    def test_missing_src_no_autofail_here(self):
        # parse_entry does not check existence — collect_binds/--mount do
        b = oc.parse_entry("/opt/some_dir", "t")
        self.assertEqual(b.dst, "/mnt/some_dir")


class PickImage(Base):
    def test_env_wins(self):
        self.assertEqual(oc.pick_image("repo:t"), "repo:t")

    def test_version_key(self):
        tags = ["2.9.1", "2.10.0", "2.1.5", "2.2"]
        self.assertEqual(max(tags, key=oc.version_key), "2.10.0")

    def test_filters_by_repo(self):
        # without the repo filter podman returns the tags of ALL images and
        # a foreign :3.22 (alpine etc.) becomes localhost/opencode:3.22
        fake = mock.Mock(returncode=0, stdout="2.1.5\n")
        with mock.patch.object(oc.subprocess, "run", return_value=fake) as run:
            img = oc.pick_image("")
        self.assertEqual(img, f"{oc.IMAGE_REPO}:2.1.5")
        self.assertIn(oc.IMAGE_REPO, run.call_args[0][0])

    def test_podman_failure_dies(self):
        bad = subprocess.CompletedProcess([], 1, "", "no such image")
        with mock.patch.object(oc.subprocess, "run", return_value=bad):
            with self.assertRaises(SystemExit) as cm:
                oc.pick_image("")
        self.assertIn("podman images failed", str(cm.exception))

    def test_podman_missing_dies(self):
        with mock.patch.object(
            oc.subprocess, "run", side_effect=FileNotFoundError("podman")
        ):
            with self.assertRaises(SystemExit) as cm:
                oc.pick_image("")
        self.assertIn("podman not found", str(cm.exception))


class ScanArgs(Base):
    def test_flags_and_tail(self):
        p, m, st, _, _, lp, child = oc.scan_args(
            [
                "--project",
                "d",
                "--mount",
                "/a",
                "--state",
                "or2",
                "run",
                "-m",
                "x/y",
                "--project-list",
                "--unknown-opencode-flag",
            ]
        )
        self.assertEqual(p, "d")
        self.assertEqual(m, ["/a"])
        self.assertEqual(st, "or2")
        self.assertFalse(lp)
        # the tail after the first foreign token ("run") goes to opencode as is
        self.assertEqual(
            child, ["run", "-m", "x/y", "--project-list", "--unknown-opencode-flag"]
        )

    def test_dash_dash(self):
        _, _, _, _, _, _, child = oc.scan_args(["--project", "d", "--", "--list"])
        self.assertEqual(child, ["--list"])

    def test_drop_flag(self):
        project, _, _, drop, _, list_projects, _ = oc.scan_args(["--drop"])
        self.assertTrue(drop)
        self.assertFalse(list_projects)

    def test_bad_state(self):
        with self.assertRaises(SystemExit) as cm:
            oc.scan_args(["--state", "a/b"])
        self.assertIn("oc:", str(cm.exception))

    def test_project_equality_form(self):
        p, _, _, _, _, _, _ = oc.scan_args(["--project=hello"])
        self.assertEqual(p, "hello")


class CollectBinds(Base):
    def test_detect_and_mounts(self):
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        binds, _, state, chosen = oc.collect_binds(None, [], proj)
        self.assertEqual(chosen, "daynews")
        self.assertEqual(state, "oc2")
        self.assertEqual(
            {b.dst for b in binds},
            {
                "/data/state/daynews",
                "/data/data/newsboat/cache.db",
                "/data/cfg/newsboat/urls",
            },
        )

    def test_deepest_match_wins(self):
        proj = self.daynews_fixture()
        self.set_profiles(
            DAYNEWS_TOML
            + textwrap.dedent(f"""
            [other]
            state = "oc9"
            paths = ["{self.home}/src"]
        """)
        )
        _, warns, _, chosen = oc.collect_binds(None, [], proj / "sub")
        self.assertEqual(chosen, "daynews")
        self.assertTrue(any("picking the deepest" in w for w in warns))

    def test_no_match(self):
        self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        _, _, state, chosen = oc.collect_binds(None, [], self.tmp)
        self.assertIsNone(chosen)
        self.assertIsNone(state)

    def test_explicit_project_from_anywhere(self):
        self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        _, _, _, chosen = oc.collect_binds("daynews", [], self.tmp)
        self.assertEqual(chosen, "daynews")

    def test_user_config_fallback(self):
        # no profiles.toml next to ./oc → the personal ~/.config/oc one is used
        (self.home / ".config/oc").mkdir(parents=True)
        (self.home / ".config/oc/profiles.toml").write_text(
            DAYNEWS_TOML.format(home=self.home)
        )
        proj = self.daynews_fixture()
        binds, _, state, chosen = oc.collect_binds(None, [], proj)
        self.assertEqual(chosen, "daynews")
        self.assertEqual(state, "oc2")

    def test_unknown_project(self):
        self.set_profiles(DAYNEWS_TOML)
        with self.assertRaises(SystemExit) as cm:
            oc.collect_binds("missing", [], self.tmp)
        self.assertIn("oc:", str(cm.exception))

    def test_mounts_include_and_cycle(self):
        self.set_profiles(
            textwrap.dedent("""
            [a]
            mounts = ["b"]
            [b]
            mounts = ["a"]
        """)
        )
        with self.assertRaises(SystemExit) as cm:
            oc.collect_binds("a", [], self.tmp)
        self.assertIn("cycle", str(cm.exception))

    def test_state_conflict(self):
        self.daynews_fixture()
        self.set_profiles(
            DAYNEWS_TOML
            + textwrap.dedent("""
            [other]
            state = "oc9"
            mounts = ["daynews"]
        """)
        )
        with self.assertRaises(SystemExit) as cm:
            oc.collect_binds("other", [], self.tmp)
        self.assertIn("conflicting state", str(cm.exception))

    def test_persistent_must_be_bool(self):
        self.set_profiles('[d]\npersistent = "yes"\n')
        with self.assertRaises(SystemExit) as cm:
            oc.collect_binds("d", [], self.tmp)
        self.assertIn("persistent must be true/false", str(cm.exception))

    def test_persistent_several_projects_ambiguous(self):
        # two persistent projects on the same state, no project resolved
        # — ambiguous owner, refuse
        self.set_profiles(
            PERSISTENT_TOML
            + textwrap.dedent("""
            [other]
            state = "oc"
            persistent = true
        """)
        )
        r = self.oc_run(["run", "hi"], cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("several projects", r.stderr)

    def test_missing_paths_warn(self):
        self.daynews_fixture()
        self.set_profiles(
            textwrap.dedent("""
            [d]
            mount = [
              "{home}/.local/state/daynews",
              "{home}/no/such/path",
            ]
        """)
        )
        binds, warns, _, chosen = oc.collect_binds("d", [], self.tmp)
        self.assertEqual(chosen, "d")
        self.assertEqual(len(binds), 1)
        self.assertTrue(any("missing" in w and "skipping" in w for w in warns))


class StateDir(Base):
    def test_target_path(self):
        want = self.home / ".local/share/oc2/profiles/or2"
        self.assertEqual(oc.state_dir("or2", migrate=False), want)

    def test_migration_of_flat_root(self):
        root = self.home / ".local/share/oc2"
        for d in ("cfg", "data", "state", "cache"):
            (root / d).mkdir(parents=True)
        got = oc.state_dir("oc", migrate=True)
        self.assertEqual(got, root / "profiles/oc")
        self.assertTrue((got / "data").is_dir())
        self.assertFalse((root / "data").exists())
        self.assertTrue((root / ".migrated").is_file())

    def test_migration_never_repeats(self):
        root = self.home / ".local/share/oc2"
        for d in ("cfg", "data"):
            (root / d).mkdir(parents=True)
        got = oc.state_dir("oc", migrate=True)
        self.assertTrue((got / "cfg").is_dir())
        # the flat dirs "came back" (a script mix-up, etc.) —
        # nothing is moved again anyway
        for d in ("cfg", "data"):
            (root / d).mkdir()
        oc.state_dir("oc2", migrate=True)
        self.assertTrue((root / "cfg").is_dir())
        self.assertFalse((root / "profiles/oc2/cfg").exists())

    def test_conflict_keeps_flat_with_warning(self):
        root = self.home / ".local/share/oc2"
        for d in ("cfg", "data"):
            (root / d).mkdir(parents=True)
        target = root / "profiles/oc"
        (target / "data/opencode").mkdir(parents=True)  # live state
        got = oc.state_dir("oc", migrate=True)
        self.assertEqual(got, target)
        self.assertTrue((target / "data/opencode").is_dir())
        self.assertTrue((root / "cfg").is_dir())  # the flat state is untouched
        self.assertTrue((root / ".migrated").is_file())  # and won't be asked again

    def test_migration_off_when_oc_data(self):
        root = self.home / ".local/share/oc2"
        (root / "cfg").mkdir(parents=True)
        custom = self.tmp / "custom-state"
        os.environ["OC_DATA"] = str(custom)
        self.assertEqual(oc.state_dir("oc", migrate=True), custom)
        self.assertTrue((root / "cfg").exists())  # untouched


class E2E(Base):
    """OC_DRY_RUN through a subprocess — the same way ./oc calls podman."""

    def test_dry_run_project_autodetect(self):
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["run", "-m", "x/y", "question"], cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("project daynews (cwd)", r.stderr)
        self.assertIn(f"{self.home}/.local/share/oc2/profiles/oc2:/data", r.stdout)
        self.assertIn(f"{self.home}/.local/state/daynews:/data/state/daynews", r.stdout)
        self.assertIn("run -m x/y question", r.stdout)  # plain token passes as is

    def test_no_tty_no_it(self):
        # the process stdin is not a tty → no -it in the command
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        e = dict(os.environ, OC_IMAGE="x:1", OC_DRY_RUN="1")
        r = subprocess.run(
            [sys.executable, str(OC), "--project-list"],
            capture_output=True,
            text=True,
            env=e,
            cwd=proj,
            stdin=subprocess.PIPE,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("-it", r.stdout)

    def test_project_list(self):
        self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--project-list"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("daynews", r.stdout)
        self.assertIn("state=oc2", r.stdout)
        # no project for the cwd → the default state is marked as such
        self.assertIn("state: oc (default)", r.stdout)
        r = self.oc_run(["--project-list"], cwd=self.home / "src/daynews")
        self.assertIn("state: oc2 (project)", r.stdout)

    def test_unknown_project_error(self):
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--project", "missing"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no project", r.stderr)

    def test_help(self):
        self.set_profiles("[x]\n")
        r = self.oc_run(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("--project-list", r.stdout)
        self.assertIn("OC_DRY_RUN", r.stdout)
        r = self.oc_run(["-h"])
        self.assertEqual(r.returncode, 0)
        # --help after `--` goes to opencode, the oc help is not printed
        r = self.oc_run(["--", "--help"])
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("--project-list", r.stdout)

    def test_project_list_hint_when_cwd_not_project(self):
        self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--project-list"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hint:", r.stdout)
        # inside a project directory there must be no hint
        r = self.oc_run(["--project-list"], cwd=self.home / "src/daynews")
        self.assertNotIn("hint:", r.stdout)

    def test_dry_run_quotes_space_args(self):
        self.set_profiles("[x]\n")
        r = self.oc_run(["run", "-m", "x/y", "question with spaces"])
        self.assertIn("'question with spaces'", r.stdout)

    def test_dry_run_persistent_container(self):
        proj = self.daynews_fixture()
        self.set_profiles(PERSISTENT_TOML)
        r = self.oc_run(["run", "-m", "x/y", "hi"], cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("podman create --name oc2-oc-daynews", r.stdout)
        self.assertIn('["sleep","infinity"]', r.stdout)
        self.assertIn("podman start oc2-oc-daynews", r.stdout)
        self.assertIn("podman exec oc2-oc-daynews run -m x/y hi", r.stdout)

    def test_dry_run_persistent_state_level(self):
        # persistence is a property of the state: even with no project
        # resolved from cwd the run reuses the named container
        self.daynews_fixture()
        self.set_profiles(PERSISTENT_TOML)
        r = self.oc_run(["run", "-m", "x/y", "hi"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("podman create --name oc2-oc-daynews", r.stdout)

    def test_dry_run_drop(self):
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--drop"], cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("podman rm -f", r.stdout)
        self.assertIn("oc2-oc2-*", r.stdout)
        self.assertIn(str(self.home / ".local/share/oc2/profiles/oc2"), r.stdout)

    def test_dry_run_drop_container_keeps_state(self):
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--drop-container"], cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("podman rm -f", r.stdout)
        self.assertIn("oc2-oc2-*", r.stdout)
        # no rm -rf of the state directory in the plan
        self.assertNotIn("rm -rf", r.stdout)

    def test_drop_requires_target(self):
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--drop"], cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--drop: resolve a target", r.stderr)

    @unittest.skipIf(shutil.which("podman"), "podman present — test is moot")
    def test_no_podman_no_image(self):
        self.set_profiles("[x]\n")  # any valid but empty config
        r = self.oc_run(["run"], env={"OC_IMAGE": "", "OC_DRY_RUN": "0"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("podman not found", r.stderr)

    def test_dry_run_has_no_side_effects(self):
        # a preview prints commands: no state directory, no migration
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(["--project", "daynews"], cwd=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("podman run --rm", r.stdout)
        self.assertFalse((self.home / ".local/share/oc2").exists())

    def test_dry_run_without_podman(self):
        # the image cannot be resolved without podman → placeholder, not an error
        proj = self.daynews_fixture()
        self.set_profiles(DAYNEWS_TOML)
        r = self.oc_run(
            ["--project", "daynews"],
            cwd=proj,
            env={"OC_IMAGE": "", "PATH": "/nonexistent"},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("localhost/opencode:<auto>", r.stdout)
        self.assertIn("dry-run: podman not found", r.stderr)

    def test_state_name_single_rule_cli(self):
        self.set_profiles("[x]\n")
        r = self.oc_run(["--state", "a b"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid state", r.stderr)

    def test_state_name_single_rule_profiles(self):
        self.set_profiles('[d]\nstate = "a/b"\n')
        with self.assertRaises(SystemExit) as cm:
            oc.collect_binds("d", [], self.tmp)
        self.assertIn("invalid state", str(cm.exception))

    def test_drift_hint_keeps_the_state(self):
        # the container mounts must match the profile exactly; the advice is
        # the least destructive one (--drop-container, not --drop)
        proj = self.daynews_fixture()
        self.set_profiles(PERSISTENT_TOML)
        os.environ["OC_IMAGE"] = "x:1"
        os.environ["OC_DRY_RUN"] = "0"
        os.chdir(proj)
        with (
            mock.patch.object(oc, "podman_present", return_value=True),
            mock.patch.object(oc, "container_binds", return_value={"x:/data"}),
            mock.patch.object(oc.sys, "argv", ["oc", "--project", "daynews"]),
            self.assertRaises(SystemExit) as cm,
        ):
            oc.main()
        msg = str(cm.exception)
        self.assertIn("not mounted:", msg)
        self.assertIn("stale:", msg)
        self.assertIn("--drop-container", msg)
        self.assertNotIn(" --drop ", msg)

    def test_podman_present_failure_is_an_error(self):
        bad = subprocess.CompletedProcess([], 2, "", "cannot connect")
        with mock.patch.object(oc.subprocess, "run", return_value=bad):
            with self.assertRaises(SystemExit) as cm:
                oc.podman_present(["podman", "ps"])
        self.assertIn("podman failed", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
