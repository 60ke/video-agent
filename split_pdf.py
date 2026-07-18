from pypdf import PdfReader, PdfWriter
import os

reader = PdfReader(r'C:\Users\CNGG\Downloads\sicpjs.pdf')
total_pages = len(reader.pages)

target_bytes = 5 * 1024 * 1024

def write_pages(start, end, path):
    w = PdfWriter()
    for i in range(start, end):
        w.add_page(reader.pages[i])
    with open(path, 'wb') as f:
        w.write(f)
    return os.path.getsize(path)

# 贪心拆分：每部分尽量接近 5MB 但不超过
parts = []
start = 0
part_num = 1

while start < total_pages:
    # 二分找当前部分最多能包含多少页
    low, high = start + 1, total_pages + 1
    best_end = start + 1
    while low < high:
        mid = (low + high) // 2
        temp_path = rf'C:\Users\CNGG\Downloads\_temp_p{part_num}.pdf'
        s = write_pages(start, mid, temp_path)
        if s <= target_bytes:
            best_end = mid
            low = mid + 1
        else:
            high = mid
        os.remove(temp_path)

    # 写最终部分
    out_path = rf'C:\Users\CNGG\Downloads\sicpjs_part{part_num}.pdf'
    s = write_pages(start, best_end, out_path)
    pages = best_end - start
    print(f'Part {part_num}: pages {start+1}-{best_end} ({pages} pages), {s/1024/1024:.2f} MB')
    parts.append((part_num, pages, s))
    start = best_end
    part_num += 1

print(f'\nTotal: {len(parts)} parts')
