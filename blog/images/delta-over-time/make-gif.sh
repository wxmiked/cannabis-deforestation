#!/usr/bin/env bash
# GIF-only, privacy-safe, with yellow year (no background pill)

set -euo pipefail

imgs=(delta-over-time-2014.png delta-over-time-2016.png delta-over-time-2018.png)

# ---- Settings ----
CROP_W=2810
CROP_H=2048
COORD_STRIP=60
RESIZE_W=700
PALETTE_COLORS=64
HOLD_DELAY=240
FADE_FRAMES=2
POINTSIZE=48
PAD_X=50
PAD_Y=15
OUTGIF="delta-over-time-corner.gif"

# Font setup for macOS
FONT_CANDIDATES=(
  "/Library/Fonts/Arial.ttf"
  "/System/Library/Fonts/Supplemental/Arial.ttf"
  "/System/Library/Fonts/Helvetica.ttc"
)
FONT=""
for f in "${FONT_CANDIDATES[@]}"; do
  if [ -f "$f" ]; then FONT="$f"; break; fi
done
[ -z "$FONT" ] && FONT="Arial"

rm -rf _cropped; mkdir _cropped

echo "Cropping, removing coordinate strip, resizing, and labeling..."
for f in "${imgs[@]}"; do
  year=$(basename "$f" .png | grep -oE '[0-9]{4}$')
  magick "$f" \
    -gravity southeast -crop "${CROP_W}x${CROP_H}+0+0" +repage \
    -gravity south -chop 0x${COORD_STRIP} \
    -strip -filter Triangle -define filter:blur=0.85 -resize ${RESIZE_W}x \
    -font "$FONT" -pointsize "$POINTSIZE" \
    -fill yellow -stroke black -strokewidth 2 \
    -gravity northeast -annotate +${PAD_X}+${PAD_Y} "$year" \
    "_cropped/$f"
done

# Preview one frame to confirm labeling
cp "_cropped/${imgs[0]}" "_cropped/preview-with-label.png"
echo "Preview saved → _cropped/preview-with-label.png"

echo "Assembling final GIF..."
magick -loop 0 -dispose previous \
  -delay $HOLD_DELAY "_cropped/${imgs[0]}" \
  \( "_cropped/${imgs[0]}" "_cropped/${imgs[1]}" -morph $FADE_FRAMES -set delay 3 \) \
  -delay $HOLD_DELAY "_cropped/${imgs[1]}" \
  \( "_cropped/${imgs[1]}" "_cropped/${imgs[2]}" -morph $FADE_FRAMES -set delay 3 \) \
  -delay $HOLD_DELAY "_cropped/${imgs[2]}" \
  -layers OptimizeFrame -layers OptimizeTransparency \
  -dither None -colors $PALETTE_COLORS "$OUTGIF"

if command -v gifsicle >/dev/null; then
  gifsicle -O3 --lossy=80 --colors $PALETTE_COLORS -o "$OUTGIF" "$OUTGIF"
fi

echo "Done → $OUTGIF"
du -h "$OUTGIF"
