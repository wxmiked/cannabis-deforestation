#!/usr/bin/env bash
# Create a vertically stacked time series image instead of GIF

set -euo pipefail

imgs=(delta-over-time-2014.png delta-over-time-2016.png delta-over-time-2018.png)

# ---- Settings ----
CROP_W=2810
CROP_H=2048
COORD_STRIP=60
RESIZE_W=700
POINTSIZE=48
PAD_X=50
PAD_Y=15
SPACING=20  # Vertical spacing between images
OUTSTACKED="delta-over-time-stacked.png"

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

echo "Stacking images vertically..."
magick "_cropped/${imgs[0]}" "_cropped/${imgs[1]}" "_cropped/${imgs[2]}" \
  -background white -splice 0x${SPACING} \
  -append \
  -chop 0x${SPACING} \
  "$OUTSTACKED"

echo "Done → $OUTSTACKED"
du -h "$OUTSTACKED"
