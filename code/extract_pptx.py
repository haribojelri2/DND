import zipfile
import xml.etree.ElementTree as ET
import sys
import os

def extract_text(path, out_path):
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return
        
    try:
        with open(out_path, 'w', encoding='utf-8') as out_f:
            with zipfile.ZipFile(path) as z:
                slides = [f for f in z.namelist() if f.startswith('ppt/slides/slide') and f.endswith('.xml')]
                
                # Sort slides by slide number
                slides.sort(key=lambda x: int(x.replace('ppt/slides/slide', '').replace('.xml', '')))
                
                for slide_name in slides:
                    out_f.write(f"--- {slide_name} ---\n")
                    xml_content = z.read(slide_name)
                    root = ET.fromstring(xml_content)
                    text = []
                    for elem in root.iter():
                        if elem.tag.endswith('}t') and elem.text:
                            text.append(elem.text)
                    if text:
                        out_f.write('\n'.join(text) + '\n')
                    out_f.write("\n")
        print(f"Extraction successful: {out_path}")
    except Exception as e:
        print(f"Error reading pptx: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        extract_text(sys.argv[1], "pptx_extracted.txt")
    else:
        print("Please provide a path to a pptx file")
