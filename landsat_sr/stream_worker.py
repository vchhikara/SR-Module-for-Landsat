"""Long-lived isolated model worker. Reads file-based block jobs from stdin."""
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onnx_worker import create_session, predict

MODEL_SHA = '3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908'

def main():
    model = Path(sys.argv[1])
    device = sys.argv[2]
    with model.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != MODEL_SHA:
            raise ValueError('Bundled model failed its integrity check.')
    backend = 'CPU'
    if device != 'cpu':
        try:
            session = create_session(model, 'gpu')
            backend = 'DirectML GPU'
        except Exception:
            if device == 'gpu': raise
            session = create_session(model, 'cpu')
    else:
        session = create_session(model, 'cpu')
    for line in sys.stdin:
        job = json.loads(line)
        if job.get('stop'): break
        response = Path(job['response'])
        try:
            image = np.load(job['input'], allow_pickle=False)
            try:
                result = predict(session, image)
            except Exception:
                if device != 'auto' or backend == 'CPU': raise
                session = create_session(model, 'cpu')
                backend = 'CPU'
                result = predict(session, image)
            np.save(job['output'], result, allow_pickle=False)
            payload = {'ok': True, 'backend': backend}
        except Exception:
            payload = {'ok': False, 'error': traceback.format_exc()[-5000:]}
        tmp = response.with_suffix('.part')
        tmp.write_text(json.dumps(payload), encoding='utf-8')
        os.replace(tmp, response)

if __name__ == '__main__': main()

