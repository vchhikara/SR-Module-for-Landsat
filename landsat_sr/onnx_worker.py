"""Offline fixed-size HAT ONNX inference, DirectML with CPU fallback."""
import json
import hashlib
from pathlib import Path
import sys
import numpy as np
import onnxruntime as ort

def starts(length, tile=64, overlap=16):
    if length <= tile: return [0]
    out=list(range(0,length-tile+1,tile-overlap))
    if out[-1] != length-tile: out.append(length-tile)
    return out

def create_session(model, device):
    options=ort.SessionOptions()
    options.enable_mem_pattern=False
    options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    providers=['CPUExecutionProvider'] if device=='cpu' else ['DmlExecutionProvider','CPUExecutionProvider']
    session=ort.InferenceSession(str(model),sess_options=options,providers=providers)
    if device=='gpu' and 'DmlExecutionProvider' not in session.get_providers():
        raise RuntimeError('DirectML GPU acceleration is unavailable on this computer.')
    return session

def predict(session, image):
    h,w=image.shape[:2]
    out=np.zeros((h*4,w*4,3),dtype=np.float32)
    total=np.zeros((h*4,w*4,1),dtype=np.float32)
    ys,xs=starts(h),starts(w)
    for y in ys:
        for x in xs:
            patch=image[y:min(y+64,h),x:min(x+64,w)]
            ph,pw=patch.shape[:2]
            patch=np.pad(patch,((0,64-ph),(0,64-pw),(0,0)),mode='edge')
            tensor=np.ascontiguousarray(patch.transpose(2,0,1)[None],dtype=np.float32)
            value=session.run(None,{'rgb':tensor})[0][0].transpose(1,2,0)[:ph*4,:pw*4]
            # Taper internal tile boundaries; normalize where overlaps meet.
            wy=np.ones(ph*4,np.float32); wx=np.ones(pw*4,np.float32)
            ramp=np.linspace(0.001,1.0,64,dtype=np.float32)
            if y>0: wy[:min(64,len(wy))]=ramp[:min(64,len(wy))]
            if y+ph<h: wy[-min(64,len(wy)):]=ramp[:min(64,len(wy))][::-1]
            if x>0: wx[:min(64,len(wx))]=ramp[:min(64,len(wx))]
            if x+pw<w: wx[-min(64,len(wx)):]=ramp[:min(64,len(wx))][::-1]
            weight=wy[:,None,None]*wx[None,:,None]
            out[y*4:(y+ph)*4,x*4:(x+pw)*4]+=value*weight
            total[y*4:(y+ph)*4,x*4:(x+pw)*4]+=weight
    return np.clip(out/np.maximum(total,1e-8),0,1)

def main():
    source,destination,weights,model,device,_=sys.argv[1:]
    image=np.load(source,allow_pickle=False)
    if image.ndim!=3 or image.shape[2]!=3: raise ValueError('Expected an RGB image')
    model_path=Path(weights)/'real_hat_64.onnx'
    if not model_path.is_file(): raise FileNotFoundError('Bundled model missing: '+str(model_path))
    with model_path.open('rb') as handle:
        digest=hashlib.file_digest(handle,'sha256').hexdigest()
    if digest!='3f47670dfeba712d68cd479f11cfe25866453c08b840269102b7a037eebc8908':  # pragma: allowlist secret
        raise ValueError('Bundled model failed its integrity check.')
    used='CPU'
    if device!='cpu':
        try:
            session=create_session(model_path,'gpu')
            result=predict(session,image)
            used='DirectML GPU'
        except Exception as exc:
            if device=='gpu': raise
            print('GPU unavailable; using CPU:',str(exc),flush=True)
            session=create_session(model_path,'cpu')
            result=predict(session,image)
    else:
        session=create_session(model_path,'cpu')
        result=predict(session,image)
    np.save(destination,result,allow_pickle=False)
    Path(destination+'.backend.json').write_text(json.dumps({'backend':used}),encoding='utf-8')
    print('Inference complete on',used,flush=True)

if __name__=='__main__': main()

