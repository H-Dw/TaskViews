"""One multimodal API request, using a generated test image rather than a desktop."""
from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw

from . import client_from_config
from ui_kobe.osworld.actions import json_object


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))["api"] if args.config else {}
    if args.model:
        config["model"] = args.model
    colors = random.sample(["red", "green", "blue", "yellow", "purple", "orange"], 2)
    image = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 50, 140, 150), fill=colors[0])
    draw.rectangle((180, 50, 300, 150), fill=colors[1])
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    with client_from_config(config) as client:
        response = client.create(messages=[{"role": "user", "content": [
            {"type": "text", "text": 'Name the colors of the two rectangles from left to right. '
             'Return JSON {"left":"English color name","right":"English color name"}.'},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                + base64.b64encode(buffer.getvalue()).decode("ascii")}},
        ]}], max_tokens=4096, response_format={"type": "json_object"})
        result = json_object(response.choices[0].message.content)
        if [str(result.get(k, "")).lower() for k in ("left", "right")] != colors:
            raise RuntimeError("Visual API probe returned an unexpected result")
        import openai
        report = {"status": "vision_api_passed", "model": client.config.model, "base_url": client.config.base_url,
                  "openai_version": openai.__version__, "colors": result, "usage": client.stats}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
