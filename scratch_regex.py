import re

patterns = {
    'mrp': r"(?:M\.?R\.?P\.?|MAXIMUM\s*RETAIL\s*PRICE|MRP|INCL\..*TAXES|INCLUSIVE.*TAXES)[^\d]{0,20}?(?:RS\.?|INR|₹)?\s*([\d\.,]{2,})",
    'net_quantity': r"(?:NET\s*(?:QTY|QUANTITY|WT|WEIGHT|VOL|VOLUME)|(?:NET\s*)?WEIGHT|CONTENT(?:S)?)[^\d]{0,20}?([\d\.]+)\s*(g|kg|ml|l|liter|litre|pieces|pcs|n)\b",
    'mfg_date': r"(?:MFG\.?\s*(?:DATE)?|PKD\.?\s*(?:DATE)?|MANUFACTURED|PACKED|DATE\s*OF\s*PACKAGING)[^\d]{0,20}?([\d]{2,4}[/\-][\d]{2,4}(?:[/\-][\d]{2,4})?|[A-Za-z]+\s*[\d]{2,4})",
    'expiry_date': r"(?:EXP(?:IRY)?\.?\s*(?:DATE)?|USE\s*(?:BY|BEFORE)|BEST\s*BEFORE)[^\d]{0,20}?([\d]{2,4}[/\-][\d]{2,4}(?:[/\-][\d]{2,4})?|[A-Za-z]+\s*[\d]{2,4}|[\d]+\s*(?:MONTHS|YEARS)\s*FROM\s*(?:MFG|PACKAGING|DATE))",
}

texts = [
    "MRP Rs 70.00",
    "Net Qty 200g",
    "Date of Packaging 14/05/25",
    "Use By 13/05/27",
    "Net Quantity 200 g",
    "Inclusive of all taxes 70.00",
    "Pkd 14/05/25"
]

for t in texts:
    for k, p in patterns.items():
        m = re.search(p, t, re.IGNORECASE)
        if m:
            print(f"{k}: matched '{t}' -> {m.group(1)}")
