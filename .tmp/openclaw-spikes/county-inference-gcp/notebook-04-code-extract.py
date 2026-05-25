# %% CELL 1
import os
import planetary_computer
import pystac_client
import requests

# %% CELL 3
import segmentation_models_pytorch as smp
import torch
import os
import requests

model = smp.DeepLabV3Plus(
    encoder_name="resnext50_32x4d",
    encoder_weights='imagenet',
    in_channels=5,
    classes=1
)

# Try MPS (Apple Silicon GPU), then CUDA (NVIDIA GPU), then CPU
if torch.backends.mps.is_available():
    device = torch.device('mps')
elif torch.cuda.is_available():
    device = torch.device('cuda')
else:
    device = torch.device('cpu')

print(f"Using device: {device}")

# Download model weights from Zenodo if not present locally
model_path = "../models/cannabis-cultivation-deeplabv3plus-resnet50-naip.pth"
zenodo_url = "https://zenodo.org/records/19343763/files/cannabis-cultivation-deeplabv3plus-resnet50-naip.pth"

if not os.path.exists(model_path):
    print(f"Model weights not found at {model_path}, downloading from Zenodo...")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    r = requests.get(zenodo_url, stream=True)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    with open(model_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                print(f"\r  {downloaded / 1e6:.1f} / {total / 1e6:.1f} MB", end="")
    print(f"\n  Saved to {model_path}")
else:
    print(f"Model weights found at {model_path}")

model = model.to(device)
model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
model.eval()
pass

# %% CELL 5
# --- User Input for Bounding Box ---
# bbox = [-120.72638195050153, 38.04185830635333, -120.63604314014556, 38.1207676113505]
# bbox = [-120.56802294590112,38.307368125981206,-120.47440785318257,38.36284893862011] # West Point
bbox = [-120.6419,38.1827,-120.44,38.3191] # West Point, south and larger
# bbox = [-120.68026045937673,38.075364038625466,-120.67004423250212,38.084287726674845] # Pool Station Rd
print('Using bounding box:', bbox)

# %% CELL 7
# --- Download NAIP Imagery ---
naip_root = '../data-to-import/microsoft/naip/calaveras-county-pool-station-rd-inference-set'
time_range = '2016-01-01/2016-12-31'  # or update as needed
catalog = pystac_client.Client.open('https://planetarycomputer.microsoft.com/api/stac/v1')
search = catalog.search(collections=['naip'], bbox=bbox, datetime=time_range)
items = search.item_collection()
print(f'Found {len(items)} NAIP items for bbox')

# Download imagery
for item in items:
    asset = item.assets['image']
    signed_href = planetary_computer.sign(asset.href)
    out_path = os.path.join(naip_root, os.path.basename(asset.href))
    if not os.path.exists(out_path):
        print(f'Downloading {out_path}')
        r = requests.get(signed_href, stream=True)
        with open(out_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    else:
        print(f'Skipping {out_path} - already exists')


# %% CELL 9
from torchgeo.datasets import RasterDataset
import rasterio
import re
from datetime import datetime
from pathlib import Path
from rtree import index as rindex
from rasterio.windows import Window
from torchgeo.datasets import BoundingBox

class MicrosoftNaip(RasterDataset):
    def __init__(self, naip_root, transforms=None):
        self.naip_root = Path(naip_root)
        self.filename_glob = "m_*.tif"
        self.filename_regex = r"^.*_.*" # (?P<date>\d{8})" # disable dates for now
        self.date_format = "%Y%m%d"
        self.is_image = True
        self.separate_files = False
        self.all_bands = ("R", "G", "B", "NIR")
        self.rgb_bands = ("R", "G", "B",)
        self.transforms = transforms

        # Build a mapping from ann_path → image_path
        self.image_paths = {}
        for img_path in self.naip_root.glob(self.filename_glob):
            self.image_paths[img_path.stem] = img_path

        super().__init__(paths=self.image_paths.values(), transforms=transforms)

        # set the dates
        dates = []
        for fname in self.image_paths.values():
            match = re.match(r"^.*_(\d{8})", fname.name)
            if match:
                date = datetime.strptime(match.group(1), "%Y%m%d")
                dates.append(date.timestamp())
        if dates:
            self.mint = min(dates)
            self.maxt = max(dates)
        else:
            self.mint = 0
            self.maxt = 9223372036854775807

    def __len__(self):
        return len(self.image_paths)

# %% CELL 10
# Define the sampler with explicit Unit type
from torchgeo.samplers import Units, GridGeoSampler
from torch.utils.data import DataLoader
import pyproj
import numpy as np

dataset = MicrosoftNaip(naip_root=naip_root)
print(dataset)

# Convert bbox (lon/lat) to projected coordinates for roi BoundingBox
import pyproj
import numpy as np

# Get the CRS of the NAIP imagery from the first file
naip_files = list(Path(naip_root).glob("*.tif"))
if naip_files:
    with rasterio.open(naip_files[0]) as src:
        dst_crs = src.crs
        print(f"NAIP CRS: {dst_crs}")

    # Define the coordinate transformations
    wgs84 = pyproj.CRS.from_epsg(4326)  # WGS84 lat/lon
    transformer = pyproj.Transformer.from_crs(wgs84, dst_crs, always_xy=True)
    
    # Convert the bbox coordinates
    # bbox format is [minx, miny, maxx, maxy] = [west, south, east, north]
    west, south, east, north = bbox
    minx, miny = transformer.transform(west, south)
    maxx, maxy = transformer.transform(east, north)
    
    print(f"Converted coordinates:")
    print(f"minx={minx}, miny={miny}, maxx={maxx}, maxy={maxy}")
    
    # Create the roi BoundingBox with the converted coordinates
    roi = BoundingBox(
        minx=minx,
        miny=miny,
        maxx=maxx,
        maxy=maxy,
        mint=dataset.mint,
        maxt=dataset.maxt,
    )
    
    print(f"New ROI: {roi}")
else:
    print("No NAIP files found to determine projection")

# Define a sampler
tile_size = 256  # Define your tile size
sampler = GridGeoSampler(
    roi=roi,
    dataset=dataset, 
    size=tile_size,
    stride=tile_size
)

def custom_collate_fn(batch):
    """Custom collate function that handles geospatial objects"""
    # Extract items that can be batched normally
    images = []
    filenames = []
    
    for item in batch:
        if "image" in item:
            images.append(item["image"])
        if "filename" in item:
            filenames.append(item["filename"])
    
    # Return a new dictionary with properly batched tensors
    result = {}
    if images:
        result["image"] = torch.stack(images)
    if filenames:
        result["filename"] = filenames
    return result

# Use the custom collate function with DataLoader
dataloader = DataLoader(
    dataset, 
    batch_size=128, 
    sampler=sampler,
    collate_fn=custom_collate_fn
)

# %% CELL 12
import segmentation_models_pytorch as smp

model = smp.DeepLabV3Plus(
    encoder_name="resnext50_32x4d",
    encoder_weights="imagenet",
    in_channels=5,
    classes=1
)

# Try MPS (Apple Silicon GPU), then CUDA (NVIDIA GPU), then CPU
if torch.backends.mps.is_available():
    device = torch.device('mps')
elif torch.cuda.is_available():
    device = torch.device('cuda')
else:
    device = torch.device('cpu')

print(f"Using device: {device}")

model = model.to(device)
model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
model.eval()

# %% CELL 13
import matplotlib.pyplot as plt
import numpy as np

def enhance_contrast(img, low_percentile=2, high_percentile=98):
    """Enhance contrast using percentile stretching - better for aerial imagery."""
    if img.ndim == 3:  # Handle multi-channel images
        out = np.zeros_like(img, dtype=float)
        for i in range(img.shape[-1]):
            channel = img[..., i]
            p_low, p_high = np.percentile(channel, (low_percentile, high_percentile))
            # Avoid division by zero
            if p_high - p_low > 1e-6:
                out[..., i] = np.clip((channel - p_low) / (p_high - p_low), 0, 1)
            else:
                out[..., i] = channel  # If constant channel, keep as is
        return out
    else:  # Handle single-channel images
        p_low, p_high = np.percentile(img, (low_percentile, high_percentile))
        if p_high - p_low > 1e-6:
            return np.clip((img - p_low) / (p_high - p_low), 0, 1)
        else:
            return img

def unnormalize(img, mean, std):
    """Unnormalize a CHW or HWC image array."""
    img = img.copy()
    mean = np.array(mean)
    std = np.array(std)
    
    # Handle CHW format (C, H, W)
    if img.shape[0] in [3, 4, 5] and len(img.shape) == 3:
        # CHW format - unnormalize then transpose
        img = img * std[:, None, None] + mean[:, None, None]
        img = img.transpose(1, 2, 0)  # Now HWC
    elif img.shape[-1] in [3, 4, 5]:  # Already HWC
        img = img * std + mean
    
    return np.clip(img, 0, 1)

def show_batch(images, preds=None, mean=None, std=None, bands=(0,1,2), enhance=True, figsize=(16, 8)):
    """
    Visualize a batch of images, masks, and (optionally) predictions.
    
    Parameters:
    -----------
    images: numpy array (B, C, H, W) or (B, H, W, C)
        Batch of images to visualize
    preds: optional, numpy array
        Predicted masks/labels
    mean, std: optional, arrays of length C
        Normalization parameters for unnormalizing
    bands: tuple
        Which bands to display as RGB (default: 0,1,2)
    enhance: bool
        Whether to apply contrast enhancement (recommended for aerial imagery)
    figsize: tuple
        Figure size in inches (width, height). Larger = higher display resolution
    """
    batch_size = images.shape[0]
    for i in range(batch_size):
        img = images[i]
        
        # Handle unnormalization if needed
        if mean is not None and std is not None:
            img_vis = unnormalize(img, mean, std)
        else:
            img_vis = img.copy()
            # Convert CHW to HWC if needed
            if len(img_vis.shape) == 3 and img_vis.shape[0] in [3, 4, 5]:
                img_vis = img_vis.transpose(1, 2, 0)
        
        # Select the specified bands
        if img_vis.shape[-1] >= max(bands) + 1:
            img_vis = img_vis[..., list(bands)]
        
        # Ensure values are in a reasonable range for visualization
        if img_vis.max() > 1.1:  # Likely 0-255 range
            img_vis = img_vis / 255.0
        
        # Clip to valid range before enhancement
        img_vis = np.clip(img_vis, 0, 1)
            
        # Apply contrast enhancement for aerial imagery
        if enhance:
            img_vis = enhance_contrast(img_vis)

        # Create plot with specified figure size
        plt.figure(figsize=figsize, dpi=100)
        
        plt.subplot(1, 2, 1)
        plt.imshow(img_vis, interpolation='nearest')  # 'nearest' preserves pixel sharpness
        plt.title(f"Image {i+1} (Bands {bands}) - {img_vis.shape[1]}x{img_vis.shape[0]}px")
        plt.axis("off")

        if preds is not None:
            pred_mask = preds[i]
            if pred_mask.ndim == 3 and pred_mask.shape[0] == 1:
                pred_mask = pred_mask[0]  # Remove channel dim if single-channel
                
            plt.subplot(1, 2, 2)
            plt.imshow(pred_mask, cmap="viridis", interpolation='nearest')
            plt.title(f"Predicted Mask - {pred_mask.shape[1]}x{pred_mask.shape[0]}px")
            plt.axis("off")
            
            # Add colorbar for predictions
            plt.colorbar(fraction=0.046, pad=0.04)
            
        plt.tight_layout()
        plt.show()

# %% CELL 15
from torchgeo.transforms import AppendNDVI

def preprocess_for_inference(images, device):
    # Fix dimension if needed
    if images.dim() == 5:  # If shape is [batch, 1, channels, height, width]
        images = images.squeeze(1)  # Now shape should be [batch, channels, height, width]
    
    # Check if we need to add NDVI channel
    if images.shape[1] == 4:  # Only 4 channels (RGB+NIR) without NDVI
        # Create NDVI transform with correct band indices
        ndvi_transform = AppendNDVI(index_red=0, index_nir=3)
        # Apply the transform to add NDVI as 5th channel
        images = ndvi_transform(images)
    
    # Apply normalization (same as training)
    num_channels = images.shape[1]
    if num_channels == 4:
        mean = torch.tensor([0.485, 0.456, 0.406, 0.5], device=images.device)
        std = torch.tensor([0.229, 0.224, 0.225, 0.2], device=images.device)
    elif num_channels == 5:  # After NDVI is added
        mean = torch.tensor([0.485, 0.456, 0.406, 0.5, 0.0], device=images.device)
        std = torch.tensor([0.229, 0.224, 0.225, 0.2, 1.0], device=images.device)
    else:
        # Default fallback
        mean = torch.ones(num_channels, device=images.device) * 0.5
        std = torch.ones(num_channels, device=images.device) * 0.2
    
    # Apply normalization: (image - mean) / std
    images = (images - mean[None, :, None, None]) / std[None, :, None, None]
        
    return images

# %% CELL 16
"""
Memory-efficient streaming inference: Process images on-the-fly without storing all in memory
"""

from tqdm.notebook import tqdm

def stream_inference(dataloader, model, device, threshold=0.5):
    """
    Stream through dataloader, run inference, and collect results without storing all images.
    Returns list of (batch_idx, image_idx_in_batch, positive_pixel_count) tuples.
    """
    model.eval()
    results = []
    
    with torch.no_grad():
        for batch_idx, batch in enumerate(tqdm(dataloader, desc="Processing batches", unit="batch")):
            images = batch["image"].to(device)
            
            # Preprocess: add NDVI and normalize for inference
            images = preprocess_for_inference(images, device)
            
            # Run inference
            outputs = model(images)
            preds = (outputs > threshold).float()
            
            # Count positive pixels for each image
            for img_idx in range(preds.shape[0]):
                count = torch.sum(preds[img_idx] > 0).item()
                global_idx = batch_idx * dataloader.batch_size + img_idx
                results.append((global_idx, count))
            
            # Free memory (works for both CUDA and MPS)
            del images, outputs, preds
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif torch.backends.mps.is_available():
                torch.mps.empty_cache()
    
    return results

print("Running streaming inference...")
# This only stores detection counts, not images - very memory efficient!
detection_results = stream_inference(dataloader, model, device, threshold=0.5)
print(f"Processed {len(detection_results)} images total")

# %% CELL 17
"""
Visualize top detections by re-reading specific images from dataloader (memory efficient)
"""

import torch
import numpy as np
import matplotlib.pyplot as plt
from tqdm.notebook import tqdm

def visualize_top_detections(detection_results, dataloader, model, device, 
                            threshold=0.5, min_pixels=100, max_visualizations=5, show_all=False):
    """
    Visualize images with significant detections by re-reading from dataloader.
    Memory efficient - only loads images needed for visualization.
    
    Args:
        detection_results: List of (image_idx, positive_pixel_count) from stream_inference
        dataloader: DataLoader to re-read images from
        model: Model for inference
        device: Device (cpu/cuda)
        threshold: Threshold for binary predictions
        min_pixels: Minimum pixels to consider significant
        max_visualizations: Max number of images to visualize
        show_all: If True, show all sorted by pixels; if False, only >= min_pixels
    """
    
    # Filter and sort results
    if show_all:
        sorted_results = sorted(detection_results, key=lambda x: x[1], reverse=True)
        significant_results = [r for r in detection_results if r[1] >= min_pixels]
        results_to_show = sorted_results[:max_visualizations]
        print(f"Showing top {len(results_to_show)} of {len(sorted_results)} images")
        print(f"(Of these, {len(significant_results)} have at least {min_pixels} positive pixels)")
    else:
        significant_results = [r for r in detection_results if r[1] >= min_pixels]
        sorted_results = sorted(significant_results, key=lambda x: x[1], reverse=True)
        results_to_show = sorted_results[:max_visualizations]
        print(f"Found {len(significant_results)} images with at least {min_pixels} pixels")
        print(f"Showing top {len(results_to_show)}")
        
        if not results_to_show:
            print(f"No images with at least {min_pixels} positive pixels found!")
            return significant_results
    
    # Print selected images
    print("\nSelected images:")
    for idx, (image_idx, count) in enumerate(results_to_show):
        print(f"{idx+1}. Image index {image_idx}: {count} positive pixels")
    
    # Get target indices to visualize
    target_indices = {idx for idx, _ in results_to_show}
    
    # Re-read only the needed images from dataloader
    selected_images = []
    selected_indices_found = []
    
    print("\nRe-reading selected images from dataloader...")
    global_idx = 0
    for batch in tqdm(dataloader, desc="Loading images"):
        images = batch["image"].to(device)
        batch_size = images.shape[0]
        
        for local_idx in range(batch_size):
            if global_idx in target_indices:
                # Store this image
                img = images[local_idx:local_idx+1]
                
                # Add NDVI for visualization
                if img.shape[1] == 4:
                    ndvi_transform = AppendNDVI(index_red=0, index_nir=3)
                    img_with_ndvi = ndvi_transform(img)
                else:
                    img_with_ndvi = img
                
                selected_images.append(img_with_ndvi.cpu())
                selected_indices_found.append(global_idx)
            
            global_idx += 1
            
            # Early exit if we found all targets
            if len(selected_indices_found) == len(target_indices):
                break
        
        if len(selected_indices_found) == len(target_indices):
            break
    
    # Concatenate and run inference on selected images
    selected_images = torch.cat(selected_images, dim=0).to(device)
    
    print(f"Running inference on {len(selected_images)} selected images...")
    with torch.no_grad():
        # Preprocess for inference
        images_norm = preprocess_for_inference(selected_images, device)
        outputs = model(images_norm)
        preds = (outputs > threshold).float()
    
    # Visualize
    imgs_np = selected_images.cpu().numpy()
    preds_np = preds.cpu().numpy()
    
    show_batch(imgs_np, preds=preds_np, mean=None, std=None, bands=(0,1,2), enhance=True, figsize=(16, 8))
    
    return significant_results

# %% CELL 18
# Visualize top detections (memory efficient - only loads selected images)
significant_results = visualize_top_detections(
    detection_results,       # Results from stream_inference
    dataloader,              # DataLoader to re-read images
    model,                   # Model
    device,                  # Device
    threshold=0.3,           # Binary threshold
    min_pixels=10000,          # Minimum pixels to consider significant
    max_visualizations=40,    # Max images to show
    show_all=False            # Show all images sorted by predictions
)

# %% CELL 20
"""
Export Cannabis Detections to KML for Google Earth
This cell processes tiles with positive detections and creates georeferenced polygons.
"""

import simplekml
from rasterio import features
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

def mask_to_polygons(mask, tile_bbox, tile_size, transformer_to_wgs84, min_area_pixels=10):
    """Convert binary mask to WGS84 polygons for KML"""
    # Ensure mask is 2D uint8
    if mask.ndim == 3:
        mask = mask.squeeze()
    mask_uint8 = (mask > 0).astype(np.uint8)
    
    # Use rasterio to extract shapes
    transform_affine = rasterio.transform.from_bounds(
        tile_bbox.minx, tile_bbox.miny, 
        tile_bbox.maxx, tile_bbox.maxy,
        tile_size, tile_size
    )
    
    shapes_gen = features.shapes(mask_uint8, mask=mask_uint8 > 0, transform=transform_affine)
    
    polygons = []
    for geom, value in shapes_gen:
        if value == 1:
            poly = shape(geom)
            
            # Calculate area in pixels
            pixel_width = (tile_bbox.maxx - tile_bbox.minx) / tile_size
            pixel_height = (tile_bbox.maxy - tile_bbox.miny) / tile_size
            pixel_area = pixel_width * pixel_height
            poly_area_pixels = poly.area / pixel_area
            
            # Filter small polygons
            if poly_area_pixels > min_area_pixels:
                # Simplify to reduce complexity
                poly_simplified = poly.simplify(tolerance=1.0, preserve_topology=True)
                
                # Transform to WGS84 for KML
                poly_wgs84 = shapely_transform(transformer_to_wgs84.transform, poly_simplified)
                polygons.append((poly_wgs84, poly_area_pixels))
    
    return polygons

# Configuration
print("=" * 80)
print("Exporting Cannabis Detections to KML")
print("=" * 80)

output_kml_path = "../results/detections/cannabis-detections-2016-partial.kml"
min_detection_pixels = 1000  # Minimum pixels to process a tile
min_polygon_area_pixels = 50  # Minimum polygon area to include
detection_threshold = 0.7

print(f"\nConfiguration:")
print(f"  Output: {output_kml_path}")
print(f"  Min detection pixels per tile: {min_detection_pixels}")
print(f"  Min polygon area: {min_polygon_area_pixels} pixels")
print(f"  Detection threshold: {detection_threshold}")

# Setup coordinate transformer to WGS84
transformer_to_wgs84 = pyproj.Transformer.from_crs(dst_crs, wgs84, always_xy=True)

# Filter tiles with significant detections
positive_tiles = [(idx, count) for idx, count in detection_results if count > min_detection_pixels]
print(f"\nFound {len(positive_tiles)} tiles with >{min_detection_pixels} pixels")

if len(positive_tiles) == 0:
    print("No significant detections found. Try lowering min_detection_pixels threshold.")
else:
    # Build mapping from index to bbox by iterating through sampler
    print("\nMapping tile indices to bounding boxes...")
    idx_to_bbox = {}
    for idx, bbox in enumerate(sampler):
        idx_to_bbox[idx] = bbox
    
    # Process tiles and extract polygons
    print("\nExtracting polygons from detected tiles...")
    kml = simplekml.Kml()
    kml.document.name = "Cannabis Detections"
    kml.document.description = f"Detected cannabis cultivation areas. Threshold: {detection_threshold}, Min pixels: {min_detection_pixels}"
    
    total_polygons = 0
    total_area_pixels = 0
    
    model.eval()
    with torch.no_grad():
        for tile_idx, pixel_count in tqdm(positive_tiles, desc="Processing detections"):
            # Get the bbox for this tile
            tile_bbox = idx_to_bbox[tile_idx]
            
            # Query the dataset for this specific tile
            sample = dataset[tile_bbox]
            image = sample["image"].unsqueeze(0).to(device)  # Add batch dimension
            
            # Preprocess and run inference
            image_preprocessed = preprocess_for_inference(image, device)
            output = model(image_preprocessed)
            pred = (output > detection_threshold).float()
            mask = pred.cpu().numpy()[0]  # Remove batch dimension
            
            # Extract polygons
            polygons = mask_to_polygons(
                mask, tile_bbox, tile_size,
                transformer_to_wgs84,
                min_area_pixels=min_polygon_area_pixels
            )
            
            # Add to KML
            for poly_wgs84, area_pixels in polygons:
                pol = kml.newpolygon()
                pol.name = f"Detection {total_polygons + 1}"
                pol.description = f"Area: {area_pixels:.1f} pixels (~{area_pixels * 4:.1f} m²)"
                
                # Extract coordinates
                if poly_wgs84.geom_type == 'Polygon':
                    coords = [(lon, lat) for lon, lat in poly_wgs84.exterior.coords]
                    pol.outerboundaryis = coords
                elif poly_wgs84.geom_type == 'MultiPolygon':
                    # Use the largest polygon
                    largest = max(poly_wgs84.geoms, key=lambda p: p.area)
                    coords = [(lon, lat) for lon, lat in largest.exterior.coords]
                    pol.outerboundaryis = coords
                
                # Style: semi-transparent red fill
                pol.style.polystyle.color = simplekml.Color.changealphaint(50, simplekml.Color.red)
                pol.style.polystyle.outline = 1
                pol.style.linestyle.color = simplekml.Color.red
                pol.style.linestyle.width = 2
                
                total_polygons += 1
                total_area_pixels += area_pixels
            
            # Free memory
            del image, image_preprocessed, output, pred, mask
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif torch.backends.mps.is_available():
                torch.mps.empty_cache()
    
    # Save KML file
    kml.save(output_kml_path)
    
    print(f"\n" + "=" * 80)
    print(f"✓ KML Export Complete!")
    print(f"=" * 80)
    print(f"  Total polygons: {total_polygons}")
    print(f"  Total area: {total_area_pixels:.1f} pixels (~{total_area_pixels * 4:.1f} m²)")
    print(f"  Output file: {output_kml_path}")
    print(f"\nOpen {output_kml_path} in Google Earth to explore the detections!")
