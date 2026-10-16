"""Download original task inputs and verify/extract the official OSWorld-1 image.

This is asset preparation only. It never starts a guest or calls a model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verified_invoice import (IMAGE_REVISION, IMAGE_ZIP_SHA256, sha, verify_task, write)  # noqa: E402
from ui_kobe.osworld.verified_tasks import TASKS, asset_files  # noqa: E402


def verify_format(path):
    with path.open('rb') as handle:
        header = handle.read(12)
    extension = path.suffix.lower()
    if not ((extension == '.pdf' and header.startswith(b'%PDF-'))
            or (extension == '.png' and header.startswith(b'\x89PNG\r\n\x1a\n'))
            or (extension == '.mp4' and header[4:8] == b'ftyp')):
        raise ValueError('Downloaded asset format differs from its official filename: ' + path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home() / 'osworld-verified/OSWorld')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', choices=tuple(TASKS), default='invoice')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--image', type=Path, default=Path.home() / 'osworld-verified/images/Ubuntu.qcow2')
    args = parser.parse_args()
    task = verify_task(args.benchmark_repo, args.task)
    assets = args.output / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    import requests
    identities = []
    for item in asset_files(task):
        name = item['name']
        path = assets / name
        if not path.exists():
            temporary = path.with_name(path.stem + '.download' + path.suffix)
            with requests.get(item['url'], timeout=(20, 120), stream=True) as response:
                response.raise_for_status()
                with temporary.open('wb') as handle:
                    for block in response.iter_content(1024 * 1024):
                        handle.write(block)
            verify_format(temporary)
            temporary.replace(path)
        verify_format(path)
        identities.append({**item, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    write(args.output / 'assets.json', {'task_key': args.task, 'files': identities, 'content_inspected': False,
                                      'gold_exposed_to_actor': False})
    if args.archive:
        if sha(args.archive) != IMAGE_ZIP_SHA256:
            raise ValueError('OSWorld-1 archive SHA256 differs from Hugging Face LFS metadata')
        if args.image.exists():
            raise FileExistsError('Do not overwrite an existing base image')
        with zipfile.ZipFile(args.archive) as archive:
            names = [item for item in archive.infolist() if item.filename.endswith('.qcow2')]
            if len(names) != 1:
                raise ValueError('Expected one official qcow2 archive member')
            member = names[0]
            args.image.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(args.image.parent).free < member.file_size + 45 * 1024**3:
                raise RuntimeError('Extraction would breach the 45 GiB disk reserve')
            partial = args.image.with_suffix('.partial')
            with archive.open(member) as source, partial.open('xb') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            # Reading to EOF verifies the ZIP CRC. Never publish a partial image.
            partial.replace(args.image)
        write(args.output / 'image-proof.json', {
            'dataset': 'xlangai/ubuntu_osworld', 'revision': IMAGE_REVISION,
            'archive': str(args.archive), 'archive_sha256': IMAGE_ZIP_SHA256,
            'archive_bytes': args.archive.stat().st_size, 'archive_member': member.filename,
            'image': str(args.image), 'image_bytes': args.image.stat().st_size,
            'image_sha256': sha(args.image), 'zip_crc_verified': True, 'vm_started': False})
    print(json.dumps({'assets': len(identities), 'image_prepared': bool(args.archive), 'vm_started': False}))


if __name__ == '__main__':
    main()
