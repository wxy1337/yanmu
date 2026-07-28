# Linux Usage

YanMu can run on Linux either directly with a Python virtual environment or through Docker.

## Direct Python Setup

Prerequisites:

- Python 3.10 or newer with `venv`
- FFmpeg available in `PATH` for best media probing and subtitle burn-in support
- For NVIDIA GPU recognition: a working NVIDIA driver plus CUDA/cuDNN runtime libraries available to the system loader

Install and start:

```bash
git clone https://github.com/wxy1337/yanmu.git
cd yanmu
chmod +x setup-linux.sh start-linux.sh
./setup-linux.sh
./start-linux.sh
```

Open:

```text
http://localhost:8000
```

The Linux setup script creates `.venv`, installs project dependencies, creates `.env` when missing, and keeps Hugging Face model downloads in `.tools/hf-home`.

## CPU Mode

CPU mode works without NVIDIA dependencies. Edit `.env`:

```env
ACCELERATION_MODE=cpu
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

## NVIDIA GPU Mode

For bare-metal Linux GPU usage, install the NVIDIA driver and CUDA/cuDNN runtime libraries first, then edit `.env`:

```env
ACCELERATION_MODE=cuda
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

If CUDA is not fully available, use `auto` while debugging:

```env
ACCELERATION_MODE=auto
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=auto
```

## Docker CPU

```bash
cp .env.example .env
docker compose up --build
```

## Docker NVIDIA GPU

Prerequisites:

- NVIDIA driver on the host
- NVIDIA Container Toolkit configured for Docker

Run:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

## Translation

The Whisper model transcribes audio and detects language. For foreign-language videos that need Simplified Chinese translation, configure a translation provider in `.env`, such as an OpenAI-compatible endpoint or LibreTranslate.
