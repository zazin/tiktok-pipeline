# 🎬 TikTok Content Generator - Full Setup Guide

Workflow lengkap untuk generate konten TikTok aesthetic dari foto produk + teks optional.

## 📋 Requirement

- Python 3.8+
- Anthropic API key (Claude untuk generate caption)
- Nano Banana API key (untuk future image generation features)

## 🚀 Quick Start (5 Menit)

### Step 1: Install Dependencies

```bash
pip install anthropic pillow requests
```

### Step 2: Set API Keys

**Option A: Via Environment Variables**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export NANO_BANANA_API_KEY="your-nano-banana-key"
export NANO_BANANA_URL="https://api.tokenrouter.com/v1"
```

**Option B: Via .env File**
Create atau edit `~/.hermes/profiles/sasha/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
NANO_BANANA_API_KEY=your-...
NANO_BANANA_URL=https://api.tokenrouter.com/v1
```

Load .env saat terminal start:
```bash
source ~/.hermes/profiles/sasha/.env
```

### Step 3: Prepare Input Folder

```bash
mkdir -p ~/my_products
# Copy semua foto produk ke folder ini
```

Structure:
```
my_products/
├── iphone-15.jpg
├── macbook-air.png
├── airpods-pro.jpg
└── metadata.tsv (optional)
```

### Step 4: Create Metadata (Optional)

Jika mau custom captions, buat `metadata.tsv`:

```
filename	text
iphone-15.jpg	Just unboxed iPhone 15! Kamera luar biasa 📱✨
macbook-air.png	MacBook Air m3 super ringan untuk content creation
airpods-pro.jpg	
```

Kosongkan field text untuk auto-generate caption.

### Step 5: Run Script

```bash
python ~/test_tiktok_generator.py \
  --input-dir ~/my_products \
  --output-dir ~/my_products/tiktok_output \
  --metadata ~/my_products/metadata.tsv
```

### Step 6: Check Output

```bash
ls ~/my_products/tiktok_output/
# Output:
# iphone-15_tiktok.png (1080x1920px)
# macbook-air_tiktok.png
# airpods-pro_tiktok.png
# log.json
```

## 📁 File Structure

```
~/.hermes/profiles/sasha/skills/creative/tiktok-content-generator/
├── SKILL.md                          # Skill documentation
├── scripts/
│   └── tiktok_batch_generator.py    # Main script
├── templates/
│   └── metadata.tsv                  # Example metadata format
└── references/
    └── QUICKSTART.md                 # Quick start guide
```

Script juga tersedia di: `~/test_tiktok_generator.py`

## 🎨 Output Design (Sasha Bytes Aesthetic)

Setiap output image:
- **Ukuran**: 1080x1920px (portrait TikTok format)
- **Background**: Soft cream (#faf5f0)
- **Product placement**: Centered, upper 70% of canvas
- **Text overlay**: Bottom with semi-transparent dark gradient
- **Typography**: Elegant serif for main text
- **Colors**: Warm golds, soft corals, natural earth tones
- **Watermark**: @sasha.bytes (bottom right)
- **Style**: Cinematic, warm, feminine, trustworthy

Contoh caption yang di-generate:
```
"Just unboxed the iPhone 15 Pro and the camera quality is absolutely insane! The ceramic shield feels so premium. ✨📱"
```

## 🔧 How It Works

1. **Input Processing**
   - Scan folder untuk semua .jpg, .png, .webp files
   - Load metadata.tsv jika ada (optional)

2. **Caption Generation**
   - Jika file tidak ada di metadata: gunakan Claude untuk generate warm, feminine caption
   - Jika ada di metadata tapi kosong: generate juga
   - Jika ada text: gunakan text itu

3. **Image Generation**
   - Load product photo → resize sesuai portrait format
   - Create canvas dengan soft cream background
   - Place product image di center, upper area
   - Add gradient overlay di bottom (untuk readability text)
   - Draw caption dengan shadow effect
   - Add watermark @sasha.bytes
   - Save as PNG 1080x1920px

4. **Logging**
   - Save log.json dengan tracking semua processed images
   - Captions, timestamps, status (success/failed)

## 📊 Example Log Output

```json
{
  "total": 3,
  "processed": 3,
  "failed": 0,
  "timestamp": "2024-11-15T10:30:45.123456",
  "results": [
    {
      "input": "iphone-15.jpg",
      "output": "iphone-15_tiktok.png",
      "caption": "Just unboxed the iPhone 15 Pro and the camera quality is absolutely insane! ✨📱",
      "timestamp": "2024-11-15T10:30:45.123456",
      "status": "success"
    }
  ]
}
```

## 🐛 Troubleshooting

### API Key Not Found
```bash
# Check if .env is loaded
echo $ANTHROPIC_API_KEY

# If empty, set manually
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Import Error: anthropic not found
```bash
pip install anthropic --upgrade
```

### Font Issues (Blurry Text)
Linux sometimes missing fonts:
```bash
sudo apt update
sudo apt install fonts-liberation fonts-dejavu -y
```

### Images Too Large/Slow
Input images yang terlalu besar akan slow:
```bash
# Resize input images to ~800px width first
convert input.jpg -resize 800x600 output.jpg
```

### Permission Denied
```bash
chmod +x ~/test_tiktok_generator.py
```

## 🚢 Next Steps: Upload ke TikTok

Script ini generate images siap untuk TikTok. Untuk upload otomatis:

1. **Manual Upload**:
   - Buka TikTok Creator Studio
   - Upload dari `~/my_products/tiktok_output/`
   - Copy caption dari log.json

2. **Firecrawl Integration** (future):
   - Script akan diperluas untuk auto-upload ke TikTok via Firecrawl
   - Status: pending (sekarang hanya image generation)

## 🎯 Usage Examples

### Example 1: Single Product with Custom Caption
```bash
mkdir -p input output
# Copy 1 image ke input/
echo -e "product.jpg\tAwesome tech review!" > input/metadata.tsv

python ~/test_tiktok_generator.py \
  --input-dir input \
  --output-dir output \
  --metadata input/metadata.tsv
```

### Example 2: Batch Processing (No Metadata)
```bash
# Copy 10 product photos ke products/
python ~/test_tiktok_generator.py \
  --input-dir products \
  --output-dir products/tiktok
# AI auto-generate captions untuk semua
```

### Example 3: Mix Manual + Auto Captions
```bash
# metadata.tsv
filename	text
hero-product.jpg	Custom caption for hero
other-1.jpg	
other-2.jpg	Another custom one
other-3.jpg	

python ~/test_tiktok_generator.py \
  --input-dir products \
  --output-dir tiktok_output \
  --metadata metadata.tsv
# AI hanya generate untuk rows yang kosong
```

## 📝 Pro Tips

1. **Best Input Image Size**: 1000-1200px width untuk quality output
2. **Metadata Format**: Tab-separated, tidak comma-separated (jangan CSV)
3. **Caption Length**: Auto-limit 2-3 lines. Lebih panjang akan wrap
4. **Batch Size**: Process 5-10 images per batch untuk stability
5. **Quality Check**: Always review 1-2 output images sebelum upload batch

## ❓ FAQ

**Q: Bisa ganti background color?**
A: Edit `COLOR_SECONDARY` di script (currently #faf5f0). Pastikan tetap warm aesthetic.

**Q: Bisa ganti font?**
A: Edit font path di script. Default pakai Liberation fonts (bold serif).

**Q: Bisa add watermark custom?**
A: Edit `watermark_text` variable di generate_overlay_image function.

**Q: Berapa lama process per image?**
A: ~2-3 detik per image (tergantung API latency untuk caption generation).

---

Siap untuk generate konten TikTok aesthetic! 🎬✨
