import contextlib,sys
from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image
from gbox import texture_cpu as CPU,texture_review as T
from gbox.registry import Unsupported
from test_texture_review import review


class Tensor:
    def __init__(self,data):self.data=data
    def unsqueeze(self,axis):return Tensor(np.expand_dims(self.data,axis))
    def float(self):return self
    def clamp(self,a,b):return Tensor(self.data.clip(a,b))
    def __getitem__(self,index):return Tensor(self.data[index])
    def permute(self,*axes):return Tensor(self.data.transpose(axes))
    def cpu(self):return self
    def numpy(self):return self.data


def test_tiled_cpu_stitch_preserves_edges_and_has_no_padding_overlap(monkeypatch):
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(inference_mode=contextlib.nullcontext,from_numpy=Tensor))
    class Model:
        input_channels=output_channels=3
        scale=2
        def __call__(self,tensor):return Tensor(tensor.data.repeat(2,axis=2).repeat(2,axis=3))
    pixels=(np.arange(13*19*3).reshape(13,19,3)%255).astype(np.uint8);progress=[]
    image=CPU.upscale(Image.fromarray(pixels),Model(),tile=7,padding=3,progress=lambda *p:progress.append(p))
    assert np.array_equal(np.asarray(image),pixels.repeat(2,axis=0).repeat(2,axis=1))
    assert progress[-1]==(6,6)


def test_cpu_runner_requires_installed_config_and_uses_isolated_bounded_process(tmp_path,monkeypatch):
    with pytest.raises(Unsupported,match='not configured'):
        T.cpu_upscale(Image.new('RGB',(4,4)),SimpleNamespace(texture_cpu_python='',texture_cpu_model=''))
    python=tmp_path/'python';python.write_bytes(b'python');model=tmp_path/'model.safetensors';model.write_bytes(b'model')
    seen=[]
    def run(args,**kw):
        seen.append((args,kw));Image.new('RGB',(16,16)).save(args[args.index('--output')+1]);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(T.subprocess,'run',run)
    image=T.cpu_upscale(Image.new('RGB',(4,4)),SimpleNamespace(texture_cpu_python=str(python),texture_cpu_model=str(model)))
    args,kw=seen[0]
    assert image.size==(16,16) and args[:2]==[str(python),'-I'] and kw['timeout']==600
    assert args[args.index('--model')+1]==str(model)
    assert not kw.get('shell')


def test_cpu_review_uses_configured_model_without_touching_the_shared_gpu_queue(review,monkeypatch,tmp_path):
    from gbox import characters as C
    import hashlib
    model=tmp_path/'installed.safetensors';model.write_bytes(b'fixture weights')
    monkeypatch.setattr(C,'library_root',lambda cfg:review.root)
    monkeypatch.setattr(C,'_local_or_fetch',lambda ctx,meta,file:review.source)
    monkeypatch.setattr(T,'cpu_upscale',lambda image,cfg:image.resize((image.width*4,image.height*4)))
    monkeypatch.setattr(T,'upscalers',lambda *_:pytest.fail('CPU AI must not submit to ComfyUI'))
    cfg=SimpleNamespace(texture_cpu_model=str(model));artifacts=[]
    ctx=SimpleNamespace(config=cfg,artifact=lambda *args,**kw:artifacts.append(args),progress=lambda *args:None)
    result=T.texture_review(T.TextureIn(character='donor',backend='cpu_ai'),ctx)['result']
    assert result['engine']=={'name':'spandrel_cpu','threads':2,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest()}
    assert result['settings']['backend']=='cpu_ai' and result['settings']['model']==model.name
    assert result['status']=='pending_approval' and result['images'][0]['size']==[1024,512]


def test_accept_keeps_cpu_model_provenance_without_changing_original(review):
    from gbox import characters as C
    engine={'name':'spandrel_cpu','threads':2,'model_sha256':'a'*64}
    job=review.store.get('job','review-job')
    job['output']['result']['engine']=engine
    review.store.put('job','review-job',job)
    original=review.source.read_bytes()
    response=review.client.post('/api/texture-reviews/review-job/decision',json={'decision':'accept'})
    assert response.status_code==200,response.text
    variant=C.get(review.root,response.json()['variant'])
    assert variant['texture_approval']['engine']==engine
    assert variant['verification']['status']=='unverified'
    assert review.source.read_bytes()==original
