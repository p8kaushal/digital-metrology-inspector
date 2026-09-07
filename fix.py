with open("src/ocr_engine.py", "r") as f:
    c = f.read()
c = c.replace("text_det_limit_side_len=1280,\n            use_mkldnn=True,\n            cpu_threads=4,\n", "text_det_limit_side_len=1280,\n")
with open("src/ocr_engine.py", "w") as f:
    f.write(c)
