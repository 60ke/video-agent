from pypdf import PdfReader
import os

reader = PdfReader(r'C:\Users\CNGG\Downloads\sicpjs.pdf')

# 检查每页的大致大小（通过单独提取）
print("Checking page sizes...")
for i in [529, 530, 531, 532, 533]:
    if i < len(reader.pages):
        p = reader.pages[i]
        # 估算：提取该页内容的大小
        from pypdf import PdfWriter
        w = PdfWriter()
        w.add_page(p)
        import io
        buf = io.BytesIO()
        w.write(buf)
        size = len(buf.getvalue())
        print(f"Page {i+1}: {size/1024/1024:.2f} MB")
