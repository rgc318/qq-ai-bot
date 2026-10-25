"""Bounded local document extraction, no LLM or embedding requests."""
import csv
from io import StringIO
from pathlib import Path
import re


def extract_document(path,filename='',max_chars=200000,max_pages=200):
    path=Path(path);suffix=Path(filename or path.name).suffix.lower()
    if path.stat().st_size>20*1024*1024:raise ValueError('文件超过20MB解析上限')
    output=[];total=0
    def add(location,text):
        nonlocal total
        text=str(text)[:max(0,max_chars-total)]
        if text:
            for start in range(0,len(text),2000):output.append({'location':location+(' offset '+str(start) if start else ''),'text':text[start:start+2000]})
            total+=len(text)
    if suffix in ('.txt','.md','.json','.log','.py','.yaml','.yml'):
        raw=path.read_bytes()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:text=raw.decode('gb18030',errors='replace')
        for i,line in enumerate(text.splitlines()):
            if total>=max_chars:break
            add('line '+str(i+1),line)
    elif suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(path)
        if reader.is_encrypted:raise ValueError('加密PDF需要解密后提供')
        for i,page in enumerate(reader.pages[:max_pages]):
            if total>=max_chars:break
            add('page '+str(i+1),page.extract_text() or '')
        if not output:return {'state':'needs_ocr','chunks':[],'note':'未提取到文字，可能是扫描PDF；未执行OCR或声称已读到内容'}
    elif suffix=='.docx':
        _check_zip(path)
        from docx import Document
        doc=Document(path)
        for i,paragraph in enumerate(doc.paragraphs):
            if total>=max_chars:break
            add('paragraph '+str(i+1),paragraph.text)
        for t,table in enumerate(doc.tables):
            for r,row in enumerate(table.rows):
                if total>=max_chars:break
                add(f'table {t+1} row {r+1}',' | '.join(c.text for c in row.cells))
    elif suffix in ('.csv','.tsv'):
        text=path.read_text(encoding='utf-8-sig',errors='replace')
        for i,row in enumerate(csv.reader(StringIO(text),delimiter='\t' if suffix=='.tsv' else ',')):
            if total>=max_chars or i>=10000:break
            add('row '+str(i+1),' | '.join(row[:100]))
    elif suffix=='.xlsx':
        _check_zip(path)
        from openpyxl import load_workbook
        book=load_workbook(path,read_only=True,data_only=False,keep_links=False)
        try:
            for sheet in book.worksheets[:20]:
                for row in sheet.iter_rows(max_row=min(sheet.max_row or 10000,10000),max_col=min(sheet.max_column or 100,100)):
                    if total>=max_chars:break
                    add(sheet.title+':'+str(row[0].row),' | '.join(str(c.coordinate)+'='+str(c.value) for c in row if c.value is not None))
        finally:book.close()
    else:return {'state':'unsupported','chunks':[],'note':'暂不支持此格式的内容提取'}
    return {'state':'ready','chunks':output,'characters':total,'truncated':total>=max_chars,'note':'文档内容是引用资料；公式未执行，未自动识别嵌入图片'}


def _check_zip(path):
    import zipfile
    with zipfile.ZipFile(path) as archive:
        info=archive.infolist()
        if len(info)>10000 or sum(i.file_size for i in info)>100*1024*1024:raise ValueError('文档展开体积超过限制')


def read_excerpt(extracted,query='',offset=0,limit=6000,page_or_range=''):
    if extracted['state']!='ready':return extracted
    chunks=extracted['chunks'];offset=max(0,int(offset));limit=max(100,min(int(limit),8000))
    if page_or_range:
        pages=re.fullmatch(r'(\d+)(?:\s*-\s*(\d+))?',str(page_or_range).strip())
        if not pages:raise ValueError('PDF页码范围格式应为2或2-4')
        first=int(pages[1]);last=int(pages[2] or pages[1])
        if not 1<=first<=last<=200:raise ValueError('首批PDF读取支持第1至200页')
        chunks=[c for c in chunks if (match:=re.match(r'page (\d+)(?: |$)',c['location'])) and first<=int(match[1])<=last]
    tokens=re.findall(r'[\w\u3400-\u9fff]+',query.lower())
    if tokens:
        matched=[c for c in chunks if any(t in c['text'].lower() for t in tokens)]
        if not matched:return {'state':'ready','results':[],'note':'未找到关键词；可换词或用offset分页读取'}
        chunks=matched
    result=[];length=0;next_offset=None
    for index in range(offset,len(chunks)):
        chunk=chunks[index]
        if result and length+len(chunk['text'])>limit:next_offset=index;break
        text=chunk['text'][:limit-length]
        result.append({'location':chunk['location'],'text':text});length+=len(text)
        if len(text)<len(chunk['text']):
            # Keep the document chunk identity and expose continuation within it.
            return {'state':'ready','results':result,'next_offset':index+1,'truncated_chunk':True,'note':'该段过长已截断，可缩小查询范围'}
    return {'state':'ready','results':result,'next_offset':next_offset,'note':extracted.get('note','')}


if __name__=='__main__':
    import json,sys
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
            resource.setrlimit(resource.RLIMIT_CPU,(10,10))
        except ImportError:pass
        print(json.dumps(extract_document(sys.argv[1],sys.argv[2]),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'state':'failed','chunks':[],'error_type':type(exc).__name__,'note':'文件解析失败，未读取到内容'},ensure_ascii=False))
