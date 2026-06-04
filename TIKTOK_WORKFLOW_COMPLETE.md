# 🎬 TikTok Content Generator - SUMMARY

Selesai! Aku sudah bikin workflow lengkap untuk generate konten TikTok aesthetic dari foto produk.

## 📦 Yang Sudah Dibuat

### 1. **Skill: tiktok-content-generator**
Lokasi: `~/.hermes/profiles/sasha/skills/creative/tiktok-content-generator/`

**Files:**
- `SKILL.md` - Dokumentasi skill
- `scripts/tiktok_batch_generator.py` - Main script untuk batch processing
- `templates/metadata.tsv` - Template contoh metadata
- `references/QUICKSTART.md` - Quick start guide

### 2. **Script Siap Pakai**
Lokasi: `~/test_tiktok_generator.py`

## 🚀 Cara Pakai (3 Langkah)

### Step 1: Setup API Keys
```bash
# Edit atau create ~/.hermes/profiles/sasha/.env
export ANTHROPIC_API_KEY="sk-a..."export NANO_BANANA_API_KEY="your..."export NANO_BANANA_URL="https://api.tokenrouter.com/v1"
```

Atau set sebagai environment variables sebelum run script.

### Step 2: Prepare Folder Input
```bash
mkdir ~/my_tiktok_products
# Copy semua foto produk ke sini
```

**Optional: Create metadata.tsv** (jika ada custom captions)
```
filename	text
photo1.jpg	Custom caption untuk photo ini
photo2.jpg	Caption lain
photo3.jpg	
```

Kosongkan cell text jika mau auto-generate caption via Claude.

### Step 3: Run Script
```bash
python ~/test_tiktok_generator.py \
  --input-dir ~/my_tiktok_products \
  --output-dir ~/my_tiktok_products/output \
  --metadata ~/my_tiktok_products/metadata.tsv
```

## 📊 Output

Setiap image output:
- **Format**: 1080x1920px (portrait TikTok standard)
- **Style**: Aesthetic Sasha Bytes (warm pastels, cinematic, feminine)
- **Include**: 
  - Product photo centered
  - Caption overlay di bottom dengan gradient
  - Watermark @sasha.bytes
  - Text shadow untuk readability
- **Quality**: PNG, high quality

Output folder structure:
```
output/
├── photo1_tiktok.png
├── photo2_tiktok.png
├── photo3_tiktok.png
└── log.json (processing log dengan captions)
```

## 🤖 AI Features

### Caption Generation (Claude)
- Jika tidak ada custom caption → Claude auto-generate warm, engaging caption
- Style: Warm, feminine, relatable, enthusiastic
- Format: 2-3 lines, TikTok-friendly
- Contoh output: "Just unboxed the iPhone 15 Pro and the camera quality is insane! ✨📱"

### Design (PIL + Brand Guidelines)
- Warm color palette (golds, creams, soft corals)
- Elegant typography (serif bold + sans regular)
- Semi-transparent gradient overlay untuk text readability
- Centered product placement
- Professional watermarking

## ⚙️ Config & Customization

**Nano Banana Setup** (untuk future image generation):
- Provider: https://api.tokenrouter.com/v1
- Model: google/gemini-3.1-flash-image-preview
- API Key: NANO_BANANA_API_KEY (di .env)

**Colors & Design** (edit di script jika perlu):
```python
COLOR_PRIMARY = (200, 160, 120)      # Warm gold
COLOR_SECONDARY = (240, 230, 210)    # Soft cream
COLOR_TEXT = (255, 255, 255)         # White
COLOR_ACCENT = (220, 140, 100)       # Warm coral
```

**Fonts** (currently):
- Main text: Liberation Serif Bold
- Watermark: Liberation Sans Regular
- Fallback: Default PIL font jika fonts tidak tersedia

## 📝 Dependencies

```
anthropic - For Claude caption generation
pillow (PIL) - For image processing
requests - For future API calls
```

Install:
```bash
pip install anthropic pillow requests
```

## 🔄 Workflow Roadmap

**✅ DONE:**
- Batch processing dari folder
- Auto-generate captions dengan Claude
- Aesthetic design overlay (Sasha Bytes style)
- Portrait TikTok format (1080x1920)
- Optional metadata.tsv support
- Processing logging

**📋 NEXT (Future):**
- Nano Banana integration untuk enhanced image generation
- Direct TikTok upload via Firecrawl
- More design templates/variations
- Video generation support
- Analytics tracking

## 💡 Pro Tips

1. **Best input image size**: 800-1200px width
2. **Metadata format**: TAB-SEPARATED (not comma)
3. **Batch size**: Process 5-10 images sekaligus untuk stability
4. **Quality**: Always review 1-2 output images sebelum upload batch
5. **Fonts**: Jika text blurry, install: `sudo apt install fonts-liberation`

## ❓ FAQ

**Q: Bisa ganti style/aesthetic?**
A: Edit COLOR_ variables dan font path di script untuk customize

**Q: Berapa lama process satu image?**
A: ~2-3 detik (tergantung API latency untuk caption generation)

**Q: Bisa auto-upload ke TikTok?**
A: Belum. Currently hanya generate images. Firecrawl integration coming soon.

**Q: Output quality OK?**
A: Yes! 1080x1920px PNG, high quality, siap langsung upload ke TikTok

## 🎯 Next Steps for Sasha

1. **Test Script:**
   ```bash
   # Copy test images
   mkdir ~/test_tiktok
   # Add some product photos
   python ~/test_tiktok_generator.py --input-dir ~/test_tiktok --output-dir ~/test_tiktok/out
   ```

2. **Review Output:**
   - Check image quality
   - Verify captions style
   - Test upload to TikTok draft

3. **Integrate Firecrawl:**
   - Once happy dengan output, add TikTok upload automation
   - Create cron job untuk batch processing kalau perlu

4. **Customize Design:**
   - Tweak colors/fonts sesuai brand guidelines
   - Add background effects jika diperlukan

## 📞 Support Files

- **Main Docs**: `/home/ubuntu/TIKTOK_SETUP.md`
- **Script**: `~/test_tiktok_generator.py`
- **Skill Dir**: `~/.hermes/profiles/sasha/skills/creative/tiktok-content-generator/`
- **Quick Start**: `~/.hermes/profiles/sasha/skills/creative/tiktok-content-generator/references/QUICKSTART.md`

---

**Status**: ✅ Ready to use!

Sekarang kamu bisa:
1. Setup API keys di .env
2. Prepare folder dengan product photos
3. Run script untuk generate TikTok content batch
4. Review output dan siap untuk upload!

Let me know kalau ada yang perlu di-tweak atau clarify! 🎬✨
