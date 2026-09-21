"""Fixed calibration-only rank-128 recipes shared by export and serving validation."""
import math

RECIPES = ('identity', 'balanced', 'activation', 'rms_weighted')
PARAMETERS = ('weight_fp4', 'weight_sf', 'alpha', 'pre_quant_scale', 'l2t_smoothed', 'l1_scaled', 'global_scale')


def stats(actual, reference):
    import torch
    if actual.shape != reference.shape: raise ValueError('Numerical shapes differ')
    error, energy, maximum = 0., 0., 0.
    for start in range(0, len(actual), 128):
        a, b = actual[start:start+128].float(), reference[start:start+128].float()
        if not torch.isfinite(a).all() or not torch.isfinite(b).all(): raise ValueError('Non-finite output')
        delta = a - b
        error += delta.double().square().sum().item()
        energy += b.double().square().sum().item()
        maximum = max(maximum, delta.abs().max().item())
    if energy <= 0: raise ValueError('Zero reference energy')
    return {'relative_l2_error': math.sqrt(error / energy), 'max_absolute_error': maximum}


def build(weight, amax, rms, recipe, seed):
    import torch
    from flashinfer import SfLayout, nvfp4_quantize
    if recipe not in RECIPES: raise ValueError('Unregistered recipe')
    if weight.dtype != torch.bfloat16 or weight.ndim != 2 or amax.shape != weight.shape[1:] or rms.shape != amax.shape:
        raise ValueError('Invalid calibration/weight layout')
    if not torch.isfinite(weight).all() or not torch.isfinite(amax).all() or not torch.isfinite(rms).all():
        raise ValueError('Non-finite calibration input')
    torch.manual_seed(seed)
    amax, rms = amax.clamp_min(1e-8), rms.clamp_min(1e-8)
    wmax = weight.float().abs().amax(dim=0).clamp_min(1e-8)
    scale = (amax / wmax).sqrt() if recipe == 'balanced' else amax.clone() if recipe == 'activation' else torch.ones_like(amax)
    scale = scale / scale.log().mean().exp()
    p = scale.reciprocal().clamp(1/256, 256).bfloat16()
    transformed = weight.float() / p.float()
    metric = rms if recipe == 'rms_weighted' else torch.ones_like(rms)
    u, s, v = torch.svd_lowrank(transformed * metric, q=144, niter=2)
    factor = s[:128].sqrt()
    l1 = (u[:, :128] * factor).bfloat16().contiguous()
    l2t = (v[:, :128] * factor / metric[:, None]).bfloat16().contiguous()
    residual = (transformed - l1.float() @ l2t.float().T).bfloat16()
    gr = (2688. / residual.float().abs().max()).reshape(1)
    rq, rsf = nvfp4_quantize(residual, gr, sfLayout=SfLayout.layout_128x4, do_shuffle=False)
    gx = (2688. / (amax * p.float()).max()).reshape(1)
    alpha = 1. / (gx * gr)
    params = {'weight_fp4': rq.view(torch.uint8), 'weight_sf': rsf.view(torch.uint8).reshape(-1),
        'alpha': alpha, 'pre_quant_scale': p,
        'l2t_smoothed': (p.float()[:, None] * l2t.float()).bfloat16().contiguous(),
        'l1_scaled': (l1.float() / alpha).bfloat16().contiguous(), 'global_scale': gx}
    for name, tensor in params.items():
        if tensor.is_floating_point() and not torch.isfinite(tensor).all():
            raise ValueError('Non-finite exported parameter: ' + name)
    return params


def apply(x, params):
    from flashinfer.gemm import svdquant_linear
    return svdquant_linear(x, **params)


def select_candidate(candidates):
    """Only calibration error is permitted in the selection input."""
    if set(candidates) != set(RECIPES): raise ValueError('Missing fixed recipe')
    if any(set(r) != {'calibration_error'} or not math.isfinite(r['calibration_error']) or r['calibration_error'] < 0 for r in candidates.values()):
        raise ValueError('Unexpected selection input')
    return min(candidates, key=lambda r: (candidates[r]['calibration_error'], r))
