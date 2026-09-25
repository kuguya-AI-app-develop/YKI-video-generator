"""Hardware profile contracts; no model process or GPU is started here."""

import json
from pathlib import Path
import tempfile
import threading
import unittest

from app.config import ROOT, load
from app.pipeline import Pipeline
from app.providers.comfy import build_workflow


class HardwareProfileTests(unittest.TestCase):
    def setUp(self):
        self.defaults = (ROOT / "config/defaults.json").read_text(encoding="utf-8")
        self.config = json.loads(self.defaults)
        self.cancel = threading.Event()
        self.pipeline = Pipeline(ROOT, self.config, None)

    def assert_option(self, command, flag, expected):
        self.assertEqual(command.count(flag), 1)
        self.assertEqual(command[command.index(flag) + 1], expected)

    def test_llama_default_and_legacy_config_fit_automatically(self):
        self.assertEqual(self.config["llama"]["gpu_layers"], "auto")
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    self.config["llama"].pop("gpu_layers")
                process = self.pipeline._llama_process(self.cancel)
                self.assert_option(process.command, "--n-gpu-layers", "auto")
                self.assert_option(process.command, "--fit", "on")
                self.assert_option(process.command, "--host", "127.0.0.1")
                self.assert_option(process.command, "--parallel", "1")
                self.assert_option(process.command, "--ctx-size", "8192")
                self.assertIsNone(process.process)
                self.assertIs(process.cancel, self.cancel)

    def test_llama_manual_gpu_layers_preserve_cpu_only_and_partial_offload(self):
        for layers in ("all", 0, 8):
            with self.subTest(layers=layers):
                self.config["llama"]["gpu_layers"] = layers
                process = self.pipeline._llama_process(self.cancel)
                self.assert_option(process.command, "--n-gpu-layers", str(layers))
                self.assert_option(process.command, "--fit", "on")
                self.assert_option(process.command, "--parallel", "1")

    def test_llama_rejects_invalid_gpu_layers(self):
        for layers in (True, False, -1, 1.5, "8", "AUTO", "", None, [], {}):
            with self.subTest(layers=layers):
                self.config["llama"]["gpu_layers"] = layers
                with self.assertRaises(ValueError):
                    self.pipeline._llama_process(self.cancel)

    def test_comfy_memory_flags_are_independent_and_opt_in(self):
        for fast_disk, disable_pinned in ((None, None), (False, False), (True, False), (False, True), (True, True)):
            with self.subTest(fast_disk=fast_disk, disable_pinned=disable_pinned):
                for key, value in (("fast_disk", fast_disk), ("disable_pinned_memory", disable_pinned)):
                    if value is None:
                        self.config["comfy"].pop(key, None)
                    else:
                        self.config["comfy"][key] = value
                process = self.pipeline._comfy_process(self.cancel)
                self.assertEqual(process.command.count("--fast-disk"), int(bool(fast_disk)))
                self.assertEqual(process.command.count("--disable-pinned-memory"), int(bool(disable_pinned)))
                self.assert_option(process.command, "--listen", "127.0.0.1")
                for flag in ("--lowvram", "--novram", "--disable-dynamic-vram"):
                    self.assertNotIn(flag, process.command)
                self.assertIsNone(process.process)

    def test_comfy_rejects_non_boolean_memory_flags(self):
        for key in ("fast_disk", "disable_pinned_memory"):
            for value in (0, 1, "false", "true", None, [], {}):
                with self.subTest(key=key, value=value):
                    self.config["comfy"][key] = value
                    with self.assertRaises(ValueError):
                        self.pipeline._comfy_process(self.cancel)
            self.config["comfy"][key] = False

    def test_experimental_profile_merges_without_changing_final_output(self):
        profile = (ROOT / "config/experimental-4070s-32gb.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "config/defaults.json").write_text(self.defaults, encoding="utf-8")
            (root / "settings.local.json").write_text(profile, encoding="utf-8")
            config = load(root)

        self.assertEqual(config["host"], "127.0.0.1")
        self.assertEqual(config["video"], self.config["video"])
        self.assertEqual((config["video"]["width"], config["video"]["height"]), (720, 1280))
        self.assertEqual(config["llama"]["context"], 8192)
        self.assertEqual(config["llama"]["gpu_layers"], "auto")
        self.assertEqual(config["llama"]["request_timeout"], 3600)
        self.assertEqual(config["comfy"]["render_timeout"], 28800)
        for section, key in (("llama", "model"), ("llama", "executable"), ("comfy", "python"), ("comfy", "directory")):
            self.assertEqual(config[section][key], self.config[section][key])

        pipeline = Pipeline(ROOT, config, None)
        llama, comfy = pipeline._llama_process(self.cancel), pipeline._comfy_process(self.cancel)
        self.assertEqual((llama.timeout, comfy.timeout), (1800, 1800))
        self.assert_option(llama.command, "--n-gpu-layers", "auto")
        self.assertIn("--fast-disk", comfy.command)
        self.assertIn("--disable-pinned-memory", comfy.command)
        cfg = config["comfy"]
        workflow = build_workflow("雨后的街角", cfg["width"], cfg["height"], 5, 0, steps=cfg["steps"])
        self.assertEqual((workflow["5"]["inputs"]["width"], workflow["5"]["inputs"]["height"]), (384, 672))
        self.assertEqual(workflow["9"]["inputs"]["steps"], 20)
        self.assertEqual((self.config["comfy"]["width"], self.config["comfy"]["height"]), (768, 1344))


if __name__ == "__main__":
    unittest.main()
