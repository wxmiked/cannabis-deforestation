"""
Improved visualization for satellite imagery and predictions
"""

import numpy as np
import matplotlib.pyplot as plt
import torch

def improved_visualization(images, masks=None, preds=None, max_images=4):
    """
    Create better visualizations for satellite imagery and predictions
    
    Args:
        images: Tensor or numpy array of shape [batch, channels, height, width]
        masks: Optional ground truth masks
        preds: Optional prediction masks
        max_images: Maximum number of images to display
    """
    # Convert to numpy if needed
    if isinstance(images, torch.Tensor):
        images = images.cpu().detach().numpy()
    if masks is not None and isinstance(masks, torch.Tensor):
        masks = masks.cpu().detach().numpy()
    if preds is not None and isinstance(preds, torch.Tensor):
        preds = preds.cpu().detach().numpy()
    
    # Determine how many images to show
    batch_size = images.shape[0]
    n_images = min(batch_size, max_images)
    
    # Set up the figure
    cols = 3 if masks is not None and preds is not None else 2 if masks is not None or preds is not None else 1
    fig, axes = plt.subplots(n_images, cols, figsize=(4*cols, 4*n_images))
    
    # Handle case of single image
    if n_images == 1:
        axes = np.array([axes])
    
    # Process each image
    for i in range(n_images):
        img = images[i]
        
        # Better RGB visualization - using proper bands and contrast enhancement
        if img.shape[0] >= 3:  # At least 3 channels
            # Standard approach: Use RGB bands (assuming order is R,G,B,NIR,...)
            rgb = img[:3]
            
            # Alternative: If using NIR-R-G bands (common in satellite imagery)
            # rgb = img[[3,0,1]]  # NIR, R, G channels
            
            # Move channels to last dimension for plotting
            rgb = np.transpose(rgb, (1, 2, 0))
            
            # Apply contrast stretching for better visualization
            p2, p98 = np.percentile(rgb, (2, 98))
            rgb_stretched = np.clip((rgb - p2) / (p98 - p2 + 1e-8), 0, 1)
            
            ax = axes[i, 0] if cols > 1 else axes[i]
            ax.imshow(rgb_stretched)
            ax.set_title(f"Image {i}")
            ax.axis("off")
            
            # If there are more than 3 channels, show NDVI in a small subplot
            if img.shape[0] >= 5:
                # Add a small subplot for NDVI visualization
                ax_ndvi = ax.inset_axes([0.65, 0.65, 0.3, 0.3])
                ndvi = img[4]  # Assuming NDVI is channel 5
                ax_ndvi.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1)
                ax_ndvi.set_title("NDVI", fontsize=8)
                ax_ndvi.axis("off")
        else:
            # For fewer channels, just show the first channel
            ax = axes[i, 0] if cols > 1 else axes[i]
            ax.imshow(img[0], cmap='gray')
            ax.set_title(f"Image {i} (1-channel)")
            ax.axis("off")
        
        # Show mask if available
        if masks is not None:
            col_idx = 1 if cols >= 2 else 0
            ax = axes[i, col_idx]
            mask = masks[i]
            if mask.shape[0] == 1:
                mask = mask[0]
            ax.imshow(mask, cmap='gray')
            ax.set_title(f"Ground Truth")
            ax.axis("off")
        
        # Show predictions if available
        if preds is not None:
            col_idx = 2 if masks is not None else 1
            ax = axes[i, col_idx]
            pred = preds[i]
            if pred.shape[0] == 1:
                pred = pred[0]
            ax.imshow(pred, cmap='viridis')
            ax.set_title(f"Prediction")
            ax.axis("off")
    
    plt.tight_layout()
    return fig

# Example usage in notebook:
"""
from improve_visualization import improved_visualization

# Get a batch
batch = next(iter(val_loader))
images = batch["image"].to(device)
masks = batch["mask"].to(device)

# Run model
with torch.no_grad():
    # Make sure NDVI is added
    if images.shape[1] == 4:
        ndvi_transform = AppendNDVI(index_red=0, index_nir=3)
        images = ndvi_transform(images)
    
    outputs = model(images)
    preds = (outputs > 0.5).float()

# Create better visualization
fig = improved_visualization(images, masks, preds)
plt.show()
"""
