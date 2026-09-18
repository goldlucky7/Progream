"""테스트 사진/ZIP 생성기 — dev/test.js 실행 전에 한 번 돌리세요."""
from PIL import Image, ImageDraw, ImageFilter
import piexif, os, random, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "testpics")
os.makedirs(OUT, exist_ok=True)

def save(im, name, dt=None):
    path = os.path.join(OUT, name)
    if dt:
        exif = piexif.dump({"Exif": {piexif.ExifIFD.DateTimeOriginal: dt.encode()}})
        im.save(path, "JPEG", quality=88, exif=exif)
    else:
        im.save(path, "JPEG" if name.endswith("jpg") else "PNG")

def scene(seed, w=800, h=600):
    random.seed(seed)
    im = Image.new("RGB", (w, h), (random.randint(40, 200), random.randint(80, 180), random.randint(60, 160)))
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = random.randint(0, w), random.randint(0, h)
        r = random.randint(8, 90)
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    return im

save(scene(1), "IMG_2024_a.jpg", "2024:05:01 10:30:00")
save(scene(2), "IMG_2024_b.jpg", "2024:05:01 11:00:00")
save(scene(3), "IMG_2024_c.jpg", "2024:05:20 18:00:00")
dup = scene(9)
save(dup, "dup_1.jpg", "2025:01:03 09:00:00")
save(dup.copy(), "dup_2.jpg", "2025:01:03 09:00:05")
b = dup.copy(); ImageDraw.Draw(b).rectangle([0, 0, 60, 40], fill=(255, 255, 255))
save(b, "dup_3_slight.jpg", "2025:01:03 09:01:00")
save(scene(11).filter(ImageFilter.GaussianBlur(9)), "blurry_1.jpg", "2025:02:10 14:00:00")
save(Image.new("RGB", (800, 600), (6, 7, 9)), "dark_1.jpg", "2025:02:11 22:00:00")
shot = Image.new("RGB", (390, 844), (240, 242, 246))
ImageDraw.Draw(shot).rectangle([0, 0, 390, 90], fill=(44, 110, 213))
shot.save(os.path.join(OUT, "Screenshot_20250315.png"), "PNG")
save(scene(21), "noexif.jpg")

# ZIP (STORE/DEFLATE 혼합 + 한글 이름 + 잡파일 — zip 불러오기 테스트용)
zp = os.path.join(HERE, "camera_test.zip")
zf = zipfile.ZipFile(zp, "w")
for i, f in enumerate(sorted(os.listdir(OUT))):
    zf.write(os.path.join(OUT, f), "Camera/" + f,
             compress_type=zipfile.ZIP_STORED if i % 2 else zipfile.ZIP_DEFLATED)
zf.write(os.path.join(OUT, "dup_1.jpg"), "Camera/한글사진.jpg", compress_type=zipfile.ZIP_DEFLATED)
zf.writestr("Camera/메모.txt", "junk data")
zf.writestr("__MACOSX/._x.jpg", "junk")
zf.close()
print("testpics:", len(os.listdir(OUT)), "files / zip:", os.path.getsize(zp), "bytes")
