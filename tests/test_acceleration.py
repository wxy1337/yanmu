import unittest

from app.media import _parse_hardware_encoders, _video_codec_args
from app.transcriber import is_cuda_runtime_error, resolve_whisper_runtime


class WhisperAccelerationTests(unittest.TestCase):
    def test_auto_uses_cuda_fp16_when_gpu_exists(self) -> None:
        self.assertEqual(
            resolve_whisper_runtime("auto", detected_cuda_devices=1),
            ("cuda", "float16"),
        )

    def test_auto_uses_cpu_int8_without_gpu(self) -> None:
        self.assertEqual(
            resolve_whisper_runtime("auto", detected_cuda_devices=0),
            ("cpu", "int8"),
        )

    def test_explicit_cuda_rejects_missing_gpu(self) -> None:
        with self.assertRaises(RuntimeError):
            resolve_whisper_runtime("cuda", detected_cuda_devices=0)

    def test_cuda_library_failure_is_recognized_for_auto_fallback(self) -> None:
        self.assertTrue(is_cuda_runtime_error(RuntimeError("Library cublas64_12.dll is not found")))
        self.assertFalse(is_cuda_runtime_error(RuntimeError("没有识别到清晰语音")))

    def test_configured_compute_type_is_kept(self) -> None:
        self.assertEqual(
            resolve_whisper_runtime(
                "cpu", configured_compute_type="float32", detected_cuda_devices=0
            ),
            ("cpu", "float32"),
        )


class VideoAccelerationTests(unittest.TestCase):
    def test_compiled_hardware_encoders_are_detected(self) -> None:
        output = """
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder
 V..... h264_qsv             H.264 / AVC / MPEG-4 AVC
 V..... libx264              libx264 H.264
"""
        result = _parse_hardware_encoders(output)
        self.assertEqual([item["encoder"] for item in result], ["h264_nvenc", "h264_qsv"])

    def test_nvenc_uses_hardware_codec(self) -> None:
        self.assertEqual(_video_codec_args("h264_nvenc")[:2], ["-c:v", "h264_nvenc"])

    def test_unknown_encoder_falls_back_to_x264(self) -> None:
        self.assertEqual(_video_codec_args("unknown")[:2], ["-c:v", "libx264"])


if __name__ == "__main__":
    unittest.main()
