import textwrap

from bench.config import all_benchmarks, load_config


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_load_config_parses_images_and_benchmarks(tmp_path):
    cfg_toml = _write(tmp_path, "config.toml", """
        openms_repo = "OpenMS"
        threads = 4
        scripts_dir = "scripts"
        results_dir = "results"
    """)
    images = _write(tmp_path, "images.yaml", """
        openms:
          build:
            context: OpenMS
            dockerfile: dockerfiles/Dockerfile
            target: tools-thirdparty
            ref: a5f59d4
            build_args: {NUM_BUILD_CORES: 4}
        fragpipe:
          pull: fragpipe:v21
    """)
    benches = _write(tmp_path, "benchmarks.yaml", """
        benchmark_types:
          - name: DDA-LFQ
            metrics:
              - {name: mean_abs_error_overall, unit: log2, required: true}
              - {name: "median_log2_ratio_*", unit: log2, required: false}
              - {name: wall_clock_s, unit: s, required: true}
            benchmarks:
              - {name: comet, image: openms, run: openms/comet.sh, input: data/pb}
              - {name: fragpipe, image: fragpipe, run: fragpipe/fragpipe.sh, input: data/pb}
    """)
    cfg = load_config(cfg_toml, images, benches)
    assert cfg.threads == 4
    assert cfg.images["openms"].kind == "build"
    assert cfg.images["openms"].ref == "a5f59d4"
    assert cfg.images["openms"].build_args == {"NUM_BUILD_CORES": "4"}
    assert cfg.images["fragpipe"].kind == "pull"
    assert cfg.images["fragpipe"].pull_ref == "fragpipe:v21"

    pairs = all_benchmarks(cfg)
    assert [b.name for _, b in pairs] == ["comet", "fragpipe"]
    bt = pairs[0][0]
    assert bt.name == "DDA-LFQ"
    assert any(m.name == "median_log2_ratio_*" and not m.required for m in bt.metrics)
    assert pairs[1][1].image == "fragpipe"


def test_image_requires_build_or_pull(tmp_path):
    cfg_toml = _write(tmp_path, "config.toml", 'openms_repo = "OpenMS"\nthreads = 2\n')
    images = _write(tmp_path, "images.yaml", "broken: {}\n")
    benches = _write(tmp_path, "benchmarks.yaml", "benchmark_types: []\n")
    try:
        load_config(cfg_toml, images, benches)
    except ValueError as e:
        assert "build" in str(e) and "pull" in str(e)
    else:
        raise AssertionError("expected ValueError for image without build/pull")
