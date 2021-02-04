import os
import cv2
import numpy as np
from PIL import Image

tessdata_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'tessdata'))
os.environ['TESSDATA_PREFIX'] = tessdata_dir

import pytesseract


def load_image(image, temp_dir='./tmp', min_width=500, dpi=300):
    """Resize image with specific dpi
    """
    if isinstance(image, str):
        image = Image.open(image)
    elif isinstance(image, np.ndarray):
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(image)

    w, h = image.size
    scale = 1 if w > min_width else min_width / w
    scale = 4
    w = int(w * scale)
    h = int(h * scale)
    image = image.resize((w, h), Image.ANTIALIAS)
    if not os.path.exists(temp_dir):
        os.mkdir(temp_dir)
    filename = os.path.join(temp_dir, 'digit_ocr.png')
    dpi = dpi if isinstance(dpi, (tuple, list)) else (dpi, dpi)
    image.save(filename, dpi=dpi)
    dpi_image = Image.open(filename)
    return dpi_image


def extract_data(image, conf_thresh=80, col_name=None, debug=False):
    """
    """
    image = load_image(image)
    rgb = np.array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)
    h_kernel = np.ones((1, int(rgb.shape[1] * 0.4)))
    detected_lines = cv2.morphologyEx(cv2.bitwise_not(thresh), cv2.MORPH_OPEN, h_kernel, iterations=1)
    and_thresh = thresh + detected_lines
    and_thresh = cv2.erode(and_thresh, np.ones((3, 3)), iterations=1)
    and_thresh = cv2.dilate(and_thresh, np.ones((5, 5)), iterations=1)
    and_thresh = cv2.erode(and_thresh, np.ones((3, 3)), iterations=1)
    if debug:
        if col_name is None:
            col_name = ''
        cv2.imwrite(f'thresh{col_name}.png', thresh)
        cv2.imwrite(f'and{col_name}.png', and_thresh)
        cv2.imwrite(f'det{col_name}.png', detected_lines)

    data = pytesseract.image_to_data(and_thresh, lang='digits_comma', config='--psm 6', output_type=pytesseract.Output.DICT)
    num_texts = len(data['level'])
    results = []
    for i in range(num_texts):
        x1, y1 = int(data['left'][i]), int(data['top'][i])
        w, h = int(data['width'][i]), int(data['height'][i])
        x2 = x1 + w
        y2 = y1 + h
        text = data['text'][i]
        conf = data['conf'][i]
        if float(conf) > conf_thresh:
            results.append((x1, y1, x2, y2, text, conf))
    return results


def draw_results(image, results):
    """
    """
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    for text_box in results:
        x1, y1, x2, y2, text,  conf = text_box
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(image, text, (x1, y2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return image
