import json
import time
import uuid
from pathlib import Path

import requests


def load_workflow(workflow_file):
    with open(workflow_file, "r", encoding="utf-8") as f:
        return json.load(f)


def submit_workflow(workflow, comfyui_url):
    response = requests.post(
        f"{comfyui_url}/prompt",
        json={
            "prompt": workflow,
            "client_id": str(uuid.uuid4())
        },
        timeout=30
    )

    response.raise_for_status()

    return response.json()["prompt_id"]


def wait_for_completion(prompt_id, comfyui_url):

    while True:

        response = requests.get(f"{comfyui_url}/history/{prompt_id}", timeout=30)

        response.raise_for_status()

        history = response.json()

        if prompt_id in history:
            return history[prompt_id]

        print("画像生成中...")

        time.sleep(1)


def download_images(history, comfyui_url, output_dir):

    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = history.get("outputs", {})

    for node_output in outputs.values():

        images = node_output.get("images", [])

        for image in images:
            response = requests.get(
                f"{comfyui_url}/view",
                params={
                    "filename": image["filename"],
                    "subfolder": image["subfolder"],
                    "type": image["type"]
                },
                timeout=60
            )

            response.raise_for_status()

            output_path = output_dir / image["filename"]

            output_path.write_bytes(response.content)

            print(f"保存完了: {output_path}")


def main():
    comfyui_url = input("ComfyUIのURLを入力してください (例: http://localhost:1234): ").strip()
    workflow_file = "image_anima_preview.json"
    output_dir = Path("generated_images")

    workflow = load_workflow(workflow_file)
    print(workflow["60:11"]["inputs"]["text"])

    if input("この内容で生成しますか？ (y/n): ").lower() != "y":
        print("キャンセルされました")
        return

    prompt_id = submit_workflow(workflow, comfyui_url)
    print(f"生成要求を送信しました: {prompt_id}")
    history = wait_for_completion(prompt_id, comfyui_url)
    download_images(history, comfyui_url, output_dir)
    print("すべて完了しました")


if __name__ == "__main__":
    main()