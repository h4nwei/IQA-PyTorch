import pytest
import pyiqa
import torch
from pyiqa.utils import imread2tensor
import pandas as pd
import numpy as np
import os

# absolute and relative tolerance of the difference between our implementation and official results
ATOL = 1e-2
RTOL = 1e-2

def read_folder(path):
    img_batch = []
    for imgname in sorted(os.listdir(path)):
        imgpath = os.path.join(path, imgname)
        imgtensor = imread2tensor(imgpath)
        img_batch.append(imgtensor)
    return torch.stack(img_batch)


def metrics_with_official_results():
    official_results = pd.read_csv('./ResultsCalibra/results_original.csv', skiprows=1).values.tolist()
    result_dict = {}
    for row in official_results:
        result_dict[row[0]] = np.array(row[1:])
    
    return result_dict

@pytest.fixture(scope='module')
def device() -> torch.device:
    return torch.device('cuda' if torch.cuda.is_available() else 'cpu')


@pytest.fixture(scope='module')
def ref_img() -> torch.Tensor:
    return read_folder('./ResultsCalibra/ref_dir')


@pytest.fixture(scope='module')
def dist_img() -> torch.Tensor:
    return read_folder('./ResultsCalibra/dist_dir')



# ==================================== Test metrics ====================================

@pytest.mark.parametrize(
        ("metric_name"),
        [(k) for k in metrics_with_official_results().keys()]
)
def test_match_official_with_given_cases(ref_img, dist_img, metric_name, device):
    official_result = metrics_with_official_results()[metric_name]
    metric = pyiqa.create_metric(metric_name, device=device)
    score = metric(dist_img, ref_img)

    if metric_name in ['niqe', 'pi', 'ilniqe'] or 'musiq' in metric_name:
        atol, rtol = 1e-2, 6e-2
    else:
        atol, rtol = ATOL, RTOL
    assert torch.allclose(score.squeeze(), torch.from_numpy(official_result).to(score), atol=atol, rtol=rtol), \
            f"Metric {metric_name} results mismatch with official results."


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GPU not available")
@pytest.mark.parametrize(
    ("metric_name"),
    [(k) for k in pyiqa.list_models() if k not in ['ahiq', 'fid', 'vsi']]
)
def test_cpu_gpu_consistency(metric_name):
    """Test if the metric results are consistent between CPU and GPU.
    ahiq, fid, vsi are not tested because:
        1. ahiq uses random patch sampling;
        2. fid requires directory inputs;
        3. vsi will output NaN with random input.
    """
    x_cpu = torch.randn(1, 3, 256, 256)
    x_gpu = x_cpu.cuda()
    y_cpu = torch.randn(1, 3, 256, 256)
    y_gpu = y_cpu.cuda()

    metric_cpu = pyiqa.create_metric(metric_name, device='cpu')
    metric_gpu = pyiqa.create_metric(metric_name, device='cuda')

    score_cpu = metric_cpu(x_cpu, y_cpu)
    score_gpu = metric_gpu(x_gpu, y_gpu)

    assert torch.allclose(score_cpu, score_gpu.cpu(), atol=ATOL, rtol=RTOL), \
        f"Metric {metric_name} results mismatch between CPU and GPU."


@pytest.mark.parametrize(
    ("metric_name"),
    [(k) for k in pyiqa.list_models() if k not in ['pi', 'nrqm', 'fid', 'mad', 'vsi']]
)
def test_gradient_backward(metric_name, device):
    """Test if the metric can be used in a gradient descent process.
    pi, nrqm and fid are not tested because they are not differentiable.
    mad and vsi give NaN with random input.
    """
    x = torch.randn(2, 3, 224, 224).to(device)
    y = torch.randn(2, 3, 224, 224).to(device)
    x.requires_grad_()

    metric = pyiqa.create_metric(metric_name, as_loss=True, device=device)
    metric.train()

    score = metric(x, y)
    if isinstance(score, tuple):
        score = score[0]
    score.sum().backward()

    assert torch.isnan(x.grad).sum() == 0, f"Metric {metric_name} cannot be used in a gradient descent process."

    if torch.cuda.is_available():
        del x
        del y
        torch.cuda.empty_cache()