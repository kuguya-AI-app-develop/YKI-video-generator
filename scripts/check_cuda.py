"""Exercise a CUDA kernel with the installed ComfyUI Python runtime."""

import json


def main():
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in the ComfyUI Python runtime.")

    device = 0
    matrix = torch.ones((32, 32), device=f"cuda:{device}")
    result = matrix @ matrix
    torch.cuda.synchronize(device)
    if not torch.all(result == 32).item():
        raise RuntimeError("The CUDA matrix multiplication returned an incorrect result.")

    print(
        json.dumps(
            {
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "device": torch.cuda.get_device_name(device),
                "capability": list(torch.cuda.get_device_capability(device)),
                "cuda_smoke": "passed",
            }
        )
    )


if __name__ == "__main__":
    main()
