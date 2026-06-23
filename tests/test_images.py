from pathlib import Path

from bench.config import ImageSpec
from bench.images import image_tag, plan_build_command


def test_image_tag_pull_is_literal():
    spec = ImageSpec(name="fragpipe", kind="pull", pull_ref="fragpipe:v21")
    assert image_tag(spec, None) == "fragpipe:v21"


def test_image_tag_build_uses_sha12():
    spec = ImageSpec(name="openms", kind="build", ref="main")
    assert image_tag(spec, "a" * 40) == "openms-bench:" + "a" * 12


def test_plan_build_command_uses_target_and_build_args():
    spec = ImageSpec(name="openms", kind="build",
                     dockerfile="dockerfiles/Dockerfile",
                     target="tools-thirdparty",
                     build_args={"NUM_BUILD_CORES": "4"})
    cmd = plan_build_command(spec, Path("/wt"), "openms-bench:abc123abc123")
    assert "build" in cmd
    assert "--target" in cmd and "tools-thirdparty" in cmd
    assert "--build-arg" in cmd and "NUM_BUILD_CORES=4" in cmd
    assert "-t" in cmd and "openms-bench:abc123abc123" in cmd
    # Dockerfile path is under the worktree; context is the worktree.
    assert any(str(Path("/wt") / "dockerfiles" / "Dockerfile") in c for c in cmd)
    assert cmd[-1] == str(Path("/wt"))
