import os
import cv2
import numpy as np
from PIL import Image

tessdata_dir = os.path.abspath(os.path.dirname(__file__))
os.environ['TESSDATA_PREFIX'] = tessdata_dir

import pytesseract
import tempfile


def show_img(img):
    cv2.namedWindow('img', cv2.WINDOW_NORMAL)
    cv2.imshow('img', img)
    cv2.waitKey(0)


def load_image(image_path, min_width=500, dpi=300):
    """Resize image with specific dpi
    """
    image = Image.open(image_path)
    w, h = image.size
    scale = 1 if w > min_width else min_width / w
    w = int(w * scale)
    h = int(h * scale)
    image = image.resize((w, h), Image.ANTIALIAS)
    temp_file = tempfile.NamedTemporaryFile(suffix='digit_ocr.png')
    filename = temp_file.name
    dpi = dpi if isinstance(dpi, (tuple, list)) else (dpi, dpi)
    image.save(filename, dpi=dpi)
    dpi_image = Image.open(filename)
    return dpi_image


image_path = 'Capture.png'
image = load_image(image_path)
rgb = np.array(image)
gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
thresh = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY)[1]

data = pytesseract.image_to_data(thresh, lang='digits_comma', config='--psm 6', output_type=pytesseract.Output.DICT)
num_texts = len(data['level'])
conf_thresh = 80
for i in range(num_texts):
    x1, y1 = int(data['left'][i]), int(data['top'][i])
    w, h = int(data['width'][i]), int(data['height'][i])
    x2 = x1 + w
    y2 = y1 + h
    text = data['text'][i]
    conf = data['conf'][i]
    if float(conf) > conf_thresh:
        cv2.rectangle(rgb, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(rgb, text, (x1, y1), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)


bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
print(rgb.shape)
show_img(bgr)
cv2.imwrite('output.png', bgr)