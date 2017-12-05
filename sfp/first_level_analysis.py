#!/usr/bin/python
"""functions to run first-level MRI analyses
"""
import pandas as pd
import numpy as np
import os
import warnings
import nibabel as nib
import itertools
import re


def _load_mgz(path):
    """load and reshape mgz so it's either 1 or 2d, instead of 3 or 4d
    """
    # see http://pandas.pydata.org/pandas-docs/version/0.19.1/gotchas.html#byte-ordering-issues
    tmp = nib.load(path).get_data().byteswap().newbyteorder()
    if tmp.ndim == 3:
        return tmp.reshape(max(tmp.shape))
    elif tmp.ndim == 4:
        return tmp.reshape(max(tmp.shape), sorted(tmp.shape)[-2])


def _arrange_mgzs_into_dict(benson_template_path, results_template_path, results_names, vareas,
                            eccen_range, eccen_bin=True, hemi_bin=True):
    mgzs = {}
    varea_mask = {'lh': _load_mgz(benson_template_path % ('lh', 'varea'))}
    varea_mask['lh'] = np.isin(varea_mask['lh'], vareas)
    varea_mask['rh'] = _load_mgz(benson_template_path % ('rh', 'varea'))
    varea_mask['rh'] = np.isin(varea_mask['rh'], vareas)

    eccen_mask = {'lh': _load_mgz(benson_template_path % ('lh', 'eccen'))}
    eccen_mask['lh'] = (eccen_mask['lh'] > eccen_range[0]) & (eccen_mask['lh'] < eccen_range[1])
    eccen_mask['rh'] = _load_mgz(benson_template_path % ('rh', 'eccen'))
    eccen_mask['rh'] = (eccen_mask['rh'] > eccen_range[0]) & (eccen_mask['rh'] < eccen_range[1])
    for hemi, var in itertools.product(['lh', 'rh'], ['varea', 'angle', 'eccen']):
        tmp = _load_mgz(benson_template_path % (hemi, var))
        mgzs['%s-%s' % (var, hemi)] = tmp[(varea_mask[hemi]) & (eccen_mask[hemi])]

    for hemi, res in itertools.product(['lh', 'rh'], results_names):
        tmp = _load_mgz(results_template_path % (res, hemi))
        res_name = os.path.split(res)[-1]
        if tmp.ndim == 1:
            mgzs['%s-%s' % (res_name, hemi)] = tmp[(varea_mask[hemi]) & (eccen_mask[hemi])]
        # some will be 2d, not 1d (since they start with 4 dimensions)
        elif tmp.ndim == 2:
            mgzs['%s-%s' % (res_name, hemi)] = tmp[(varea_mask[hemi]) & (eccen_mask[hemi]), :]

    if eccen_bin:
        for hemi in ['lh', 'rh']:
            bin_masks = []
            for i in range(*eccen_range):
                bin_masks.append((mgzs['eccen-%s' % hemi] > i) & (mgzs['eccen-%s' % hemi] < i+1))
            for res in results_names + ['varea', 'angle', 'eccen']:
                res_name = os.path.split(res)[-1]
                tmp = mgzs['%s-%s' % (res_name, hemi)]
                mgzs['%s-%s' % (res_name, hemi)] = np.array([tmp[m].mean(0) for m in bin_masks])
        if hemi_bin:
            mgzs_tmp = {}
            for res in results_names + ['varea', 'angle', 'eccen']:
                res_name = os.path.split(res)[-1]
                mgzs_tmp[res_name] = np.mean([mgzs['%s-lh' % res_name], mgzs['%s-rh' % res_name]], 0)
            mgzs = mgzs_tmp
    return mgzs


def _unfold_2d_mgz(mgz, value_name, variable_name, mgz_name, hemi=None):
    tmp = pd.DataFrame(mgz)
    tmp = pd.melt(tmp.reset_index(), id_vars='index')
    if hemi is not None:
        tmp['hemi'] = hemi
    tmp = tmp.rename(columns={'index': 'voxel', 'variable': variable_name, 'value': value_name})
    if 'models_class' in mgz_name:
        # then the value name contains which stimulus class this and the actual value_name is
        # amplitude_estimate
        class_idx = re.search('models_class_([0-9]+)', mgz_name).groups()
        assert len(class_idx) == 1, "models_class title %s should only contain one number, to identify stimulus class!" % value_name
        tmp['stimulus_class'] = int(class_idx[0])
    return tmp


def _add_freq_metainfo(design_df):
    """this function takes the design_df and adds some metainfo based on the stimulus frequency

    right now these are: stimulus_superclass (radial, circular, etc), freq_space_angle (the angle
    in our 2d frequency space) and freq_space_distance (distance from the origin in our 2d
    frequency space)
    """
    # stimuli belong to five super classes, or paths through the frequency space: w_r=0; w_a=0;
    # w_r=w_a; w_r=-w_a; and sqrt(w_r^2 + w_a^)=32. We want to be able to look at them separately,
    # so we label them (this is inefficient but works). We also want to get some other identifying
    # values. We do this all at once because the major time cost comes from applying this to all
    # rows, not the computations themselves
    def freq_identifier(x):
        if x.w_r == 0 and x.w_a != 0:
            sc = 'radial'
        elif x.w_r != 0 and x.w_a == 0:
            sc = 'circular'
        elif x.w_r == x.w_a:
            sc = 'forward spiral'
        elif x.w_r == -x.w_a:
            sc = 'reverse spiral'
        else:
            sc = 'mixtures'
        try:
            ang = np.arctan(x.w_r / x.w_a)
        except ZeroDivisionError:
            ang = np.arctanh(x.w_a / x.w_r)
        return sc, ang, np.sqrt(x.w_r**2 + x.w_a**2)

    properties_list = design_df[['w_r', 'w_a']].apply(freq_identifier, 1)
    sc = pd.Series([i[0] for i in properties_list.values], properties_list.index)
    ang = pd.Series([i[1] for i in properties_list.values], properties_list.index)
    dist = pd.Series([i[2] for i in properties_list.values], properties_list.index)

    design_df['stimulus_superclass'] = sc
    design_df['freq_space_angle'] = ang
    design_df['freq_space_distance'] = dist
    return design_df


def _setup_mgzs_for_df(mgzs, results_names, df_mode, hemi=None):
    df = None
    if hemi is None:
        mgz_key = '%s'
    else:
        mgz_key = '%s-{}'.format(hemi)
    for brain_name in results_names:
        if df_mode == 'summary':
            value_name = {'modelmd': 'amplitude_estimate_median',
                          'modelse': 'amplitude_estimate_std_error'}.get(brain_name)
            tmp = _unfold_2d_mgz(mgzs[mgz_key % brain_name], value_name,
                                 'stimulus_class', brain_name, hemi)
        elif df_mode == 'full':
            tmp = _unfold_2d_mgz(mgzs[mgz_key % brain_name], 'amplitude_estimate',
                                 'bootstrap_num', brain_name, hemi)
        if df is None:
            df = tmp
        else:
            if df_mode == 'summary':
                df = df.set_index(['voxel', 'stimulus_class'])
                tmp = tmp.set_index(['voxel', 'stimulus_class'])
                df[value_name] = tmp[value_name]
                df = df.reset_index()
            elif df_mode == 'full':
                df = pd.concat([df, tmp])

    df = df.set_index('voxel')
    for brain_name in ['varea', 'eccen', 'angle', 'R2']:
        tmp = pd.DataFrame(mgzs[mgz_key % brain_name])
        tmp.index.rename('voxel', True)
        df[brain_name] = tmp[0]

    df = df.reset_index()
    return df


def _put_mgzs_dict_into_df(mgzs, design_df, results_names, df_mode, eccen_bin=True, hemi_bin=True):
    if not hemi_bin:
        df = {}
        for hemi in ['lh', 'rh']:
            df[hemi] = _setup_mgzs_for_df(mgzs, results_names, df_mode, hemi)

        # because python 0-indexes, the minimum voxel number is 0. thus if we were to just add the
        # max, the min in the right hemi would be the same as the max in the left hemi
        df['rh'].voxel = df['rh'].voxel + df['lh'].voxel.max()+1
        df = pd.concat(df).reset_index(0, drop=True)
    else:
        df = _setup_mgzs_for_df(mgzs, results_names, df_mode, None)

    # Add the stimulus frequency information
    design_df = _add_freq_metainfo(design_df)

    df = df.set_index('stimulus_class')
    df = df.join(design_df)
    df = df.reset_index().rename(columns={'index': 'stimulus_class'})

    if eccen_bin:
        df['eccen'] = df['eccen'].apply(lambda x: '%i-%i' % (np.floor(x), np.ceil(x)))
    return df


def _find_closest_to(a, bs):
    idx = np.argmin(np.abs(np.array(bs) - a))
    return bs[idx]


def _round_freq_space_distance(df, core_distances=[6, 8, 11, 16, 23, 32, 45, 64, 91, 128, 181]):
    df['rounded_freq_space_distance'] = df.freq_space_distance.apply(_find_closest_to,
                                                                     bs=core_distances)
    return df


def create_GLM_result_df(design_df, benson_template_path, results_template_path,
                         df_mode='summary', save_path=None, class_nums=xrange(52), vareas=[1],
                         eccen_range=(2, 8), eccen_bin=True, hemi_bin=True):
    """this loads in the realigned mgz files and creates a dataframe of their values

    This only returns those voxels that lie within visual areas outlined by the Benson14 varea mgz

    this should be run after GLMdenoise and after realign.py. The mgz files you give the path to
    should be surfaces, not volumes. this will take a while to run, which is why it's recommended
    to provide save_path so the resulting dataframe can be saved.

    design_df: output of create_design_df

    benson_template_path: template path to the Benson14 mgz files, containing two string formatting
    symbols (%s; one for hemisphere, one for variable [angle, varea, eccen]),
    e.g. /mnt/Acadia/Freesurfer_subjects/wl_subj042/surf/%s.benson14_%s.mgz

    results_template_path: template path to the results mgz files (outputs of realign.py),
    containing two string formatting symbols (%s; one for hemisphere, one for results_names)

    df_mode: 'summary' or 'full'. If 'summary', will load in the 'modelmd' and 'modelse' mgz files,
    using those calculated summary values. If 'full', will load in the 'models_class_##' mgz files,
    containing the info to calculate central tendency and spread directly. In both cases, 'R2' will
    also be loaded in. Assumes modelmd and modelse lie directly in results_template_path and that
    models_class_## files lie within the subfolder models_niftis

    save_path: None or str. if str, will save the GLM_result_df at this location

    class_nums: list of ints. if df_mode=='full', which classes to load in. If df_mode=='summary',
    then this is ignored.

    vareas: list of ints. Which visual areas to include. the Benson14 template numbers vertices 0
    (not a visual area), -3, -2 (V3v and V2v, respectively), and 1 through 7.

    eccen_range: 2-tuple of ints or floats. What range of eccentricities to include.

    eccen_bin: boolean, default True. Whether to bin the eccentricities in integer
    increments. HIGHLY RECOMMENDED to be True if df_mode=='full', otherwise this will take much
    longer and the resulting DataFrame will be absurdly large and unwieldy.

    hemi_bin: boolean, default True. Does nothing if eccen_bin is False, but if eccen_bin is True,
    average corresponding eccentricity ROIs across the two hemispheres. Generally, this is what you
    want, unless you also to examine differences between the two hemispheres.
    """
    if df_mode == 'summary':
        results_names = ['modelse', 'modelmd']
    elif df_mode == 'full':
        results_names = ['models_niftis/models_class_%02d' % i for i in class_nums]
        if not eccen_bin:
            warnings.warn("Not binning by eccentricities while constructing the full DataFrame is "
                          "NOT recommended! This may fail because you run out of memory!")
    else:
        raise Exception("Don't know how to construct df with df_mode %s!" % df_mode)
    if hemi_bin and not eccen_bin:
        warnings.warn("You set eccen_bin to False but hemi_bin to True. I can only bin across "
                      "hemispheres if also binning eccentricities!")
        hemi_bin = False
    mgzs = _arrange_mgzs_into_dict(benson_template_path, results_template_path,
                                   results_names+['R2'], vareas, eccen_range, eccen_bin, hemi_bin)
    results_names = [os.path.split(i)[-1] for i in results_names]

    df = _put_mgzs_dict_into_df(mgzs, design_df, results_names, df_mode, eccen_bin, hemi_bin)
    core_dists = df[df.stimulus_superclass == 'radial'].freq_space_distance.unique()
    df = _round_freq_space_distance(df, core_dists)

    if save_path is not None:
        df.to_csv(save_path)

    return df


# Make wrapper function that does above, loading in design_df and maybe grabbing it for different
# results? and then combining them.
