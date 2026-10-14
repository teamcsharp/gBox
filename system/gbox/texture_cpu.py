"""Isolated, tiled CPU inference using an installed Spandrel image model.

Invoked with the configured inference Python; does not import or interrupt ComfyUI.
"""
from pathlib import Path


def upscale(image, model, *, tile=128, padding=16, progress=lambda *_:None):
    import numpy as np
    import torch
    from PIL import Image
    if model.input_channels!=3 or model.output_channels!=3 or model.scale not in (2,3,4):
        raise ValueError('Choose an installed RGB image upscaler with a 2x, 3x or 4x scale')
    image=image.convert('RGB');width,height=image.size;scale=model.scale
    result=Image.new('RGB',(width*scale,height*scale))
    total=((width+tile-1)//tile)*((height+tile-1)//tile);done=0
    with torch.inference_mode():
        for top in range(0,height,tile):
            for left in range(0,width,tile):
                right,bottom=min(left+tile,width),min(top+tile,height)
                x,y=max(0,left-padding),max(0,top-padding)
                r,b=min(width,right+padding),min(height,bottom+padding)
                data=np.asarray(image.crop((x,y,r,b)),dtype=np.float32)/255
                tensor=torch.from_numpy(data.transpose(2,0,1).copy()).unsqueeze(0)
                pixels=model(tensor).float().clamp(0,1)[0].permute(1,2,0).cpu().numpy()
                patch=Image.fromarray(np.rint(pixels*255).astype(np.uint8))
                patch=patch.crop(((left-x)*scale,(top-y)*scale,(right-x)*scale,(bottom-y)*scale))
                result.paste(patch,(left*scale,top*scale));done+=1;progress(done,total)
    return result


def main():
    import argparse
    import torch
    from PIL import Image
    from spandrel import ModelLoader,ImageModelDescriptor
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True)
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    model=ModelLoader(device='cpu').load_from_file(Path(args.model))
    if not isinstance(model,ImageModelDescriptor):raise ValueError('The configured model is not an image upscaler')
    model.cpu().eval()
    with Image.open(args.input) as source:
        if source.width*source.height>4_194_304:raise ValueError('CPU preview input exceeds four megapixels')
        result=upscale(source,model)
        result.save(args.output,format='PNG')


if __name__=='__main__':main()
