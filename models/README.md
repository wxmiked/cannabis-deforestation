# Model Weights

The trained model weights for this project are not stored in this repository (they are excluded via `.gitignore`).

## Download

Model weights are archived on Zenodo with a permanent DOI:

**[cannabis-cultivation-segmentation-v1 on Zenodo](https://doi.org/10.5281/zenodo.19343763)**

`https://doi.org/10.5281/zenodo.19343763`

The Zenodo record includes the model weights file (`cannabis-cultivation-deeplabv3plus-resnet50-naip.pth`) and a full description of the model architecture, training data, usage instructions, and known limitations.

## Expected location

After downloading, place the weights file here:

```
models/cannabis-cultivation-deeplabv3plus-resnet50-naip.pth
```

The training and inference notebook at `notebooks/cannabis-segmentation-torchgeo.ipynb` expects the file at this path.
