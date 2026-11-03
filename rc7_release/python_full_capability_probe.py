"""Standalone offline full-Python payload probe, run by the packaged interpreter."""
from __future__ import annotations
import argparse,importlib,importlib.metadata,json,socket,sys,tempfile
from pathlib import Path

DISTRIBUTIONS={
    'pytest':'pytest','requests':'requests','docx':'python-docx','openpyxl':'openpyxl',
    'pptx':'python-pptx','pypdf':'pypdf','numpy':'numpy','cv2':'opencv-python-headless',
    'PIL':'pillow','onnxruntime':'onnxruntime','rapidocr_onnxruntime':'rapidocr-onnxruntime',
}


def probe(runtime_root):
    root=Path(runtime_root).resolve()
    try:Path(sys.executable).resolve().relative_to(root)
    except ValueError:raise RuntimeError('FULL_PYTHON_PACKAGE_INTERPRETER_REQUIRED')
    def deny(*args,**kwargs):raise RuntimeError('FULL_PYTHON_PROBE_NETWORK_FORBIDDEN')
    socket.create_connection=deny;socket.socket.connect=deny;socket.socket.connect_ex=deny
    modules={};versions={}
    for module,distribution in DISTRIBUTIONS.items():
        loaded=importlib.import_module(module)
        try:Path(loaded.__file__).resolve().relative_to(root)
        except (ValueError,TypeError):raise RuntimeError('FULL_PYTHON_HOST_DEPENDENCY_FORBIDDEN:'+module)
        modules[module]=loaded;versions[distribution]=importlib.metadata.version(distribution)
    from docx import Document
    from openpyxl import Workbook,load_workbook
    from pptx import Presentation
    from pptx.util import Inches
    from pypdf import PdfWriter,PdfReader
    from PIL import Image,ImageDraw,ImageFont
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='rc72-offline-python-') as temporary:
        directory=Path(temporary);token='RC72 OFFLINE'
        document=Document();document.add_paragraph(token);document.save(str(directory/'check.docx'))
        assert Document(str(directory/'check.docx')).paragraphs[0].text==token
        workbook=Workbook();workbook.active['A1']=token;workbook.save(str(directory/'check.xlsx'))
        loaded=load_workbook(str(directory/'check.xlsx'));assert loaded.active['A1'].value==token;loaded.close()
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1),Inches(1),Inches(4),Inches(1)).text_frame.text=token
        deck.save(str(directory/'check.pptx'));assert Presentation(str(directory/'check.pptx')).slides[0].shapes[0].text==token
        writer=PdfWriter();writer.add_blank_page(width=128,height=128)
        with (directory/'check.pdf').open('wb') as stream:writer.write(stream)
        assert len(PdfReader(str(directory/'check.pdf')).pages)==1
        image=Image.new('RGB',(220,40),'white');ImageDraw.Draw(image).text((8,8),token,font=ImageFont.load_default(),fill='black')
        image=image.resize((1100,200))
        # Explicit one-thread CPU sessions avoid relying on a host accelerator.
        engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1)
        result,timing=engine(np.asarray(image))
        if not result or not any(str(row[1]).strip() for row in result):raise RuntimeError('FULL_PYTHON_OFFLINE_OCR_INFERENCE_REQUIRED')
        return dict(schema='RC72_FULL_PYTHON_CAPABILITY_V1',status='PASS',runtime_root=str(root),
            interpreter=str(Path(sys.executable).resolve()),versions=versions,
            evidence_level='ACTUAL_PACKAGE_LOCAL_OFFLINE_EXECUTION',network_allowed=False,
            qualification_scope='ENGINEERING_PAYLOAD_CAPABILITY',field_verified=False,bank_final=False,
            roundtrips=['DOCX','XLSX','PPTX','PDF'],offline_ocr_inference_executed=True,ocr_regions=len(result))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-root',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:result=probe(args.runtime_root)
    except Exception as exc:
        result=dict(schema='RC72_FULL_PYTHON_CAPABILITY_V1',status='FAIL',error=str(exc),error_type=type(exc).__name__,network_allowed=False)
    Path(args.output).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,sort_keys=True));return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
