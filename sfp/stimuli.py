#!/usr/bin/python
"""script to generate stimuli
"""
import pyPyrTools as ppt
import numpy as np
from matplotlib import pyplot as plt
import itertools
import pandas as pd
import seaborn as sns
import warnings
from scipy import misc as smisc
import os
import argparse


def log_polar_grating(size, alpha, w_r=0, w_a=0, phi=0, ampl=1, origin=None, scale_factor=1):
    """Make a sinusoidal grating in logPolar space.

    this allows for the easy creation of stimuli whose spatial frequency decreases with
    eccentricity, as the peak spatial frequency of neurons in the early visual cortex does.

    Examples
    ============

    circular: `log_polar_grating(512, 4, 10)`

    radial: `log_polar_grating(512, 4, w_a=10)`

    spiral: `log_polar_grating(512, 4, 10, 10)`

    plaid: `log_polar_grating(512, 4, 10) + log_polar_grating(512, 4, w_a=10)`


    Parameters
    =============

    size: scalar. size of the image (only square images permitted).

    alpha: int, radius (in pixel spacing) of the "fovea".  IE: log_rad = log(r^2 + alpha^2)

    w_r: int, logRadial frequency.  Units are matched to those of the angular frequency (`w_a`).

    w_a: int, angular frequency.  Units are cycles per revolution around the origin.

    phi: int, phase (in radians).

    ampl: int, amplitude

    origin: 2-tuple of floats, the origin of the image, from which all distances will be measured
    and angles will be relative to. By default, the center of the image

    scale_factor: int or float. how to scale the distance from the origin before computing the
    grating. this is most often done for checking aliasing; e.g., set size_2 = 100*size_1 and
    scale_factor_2 = 100*scale_factor_1. then the two gratings will have the same pattern, just
    sampled differently
    """
    assert not hasattr(size, '__iter__'), "Only square images permitted, size must be a scalar!"
    rad = ppt.mkR(size, origin=origin)/scale_factor
    # if the origin is set such that it lies directly on a pixel, then one of the pixels will have
    # distance 0 and, if alpha is also 0, that means we'll have a -inf out of np.log2 and thus a
    # nan from the cosine. this little hack avoids that issue.
    if alpha == 0 and 0 in rad:
        rad += 1e-12
    lrad = np.log2(rad**2 + alpha**2)
    theta = ppt.mkAngle(size, origin=origin)

    return ampl * np.cos((w_r/np.pi) * lrad + w_a * theta + phi)


def _create_better_sampled_grating(orig_size, alpha, w_r=0, w_a=0, phi=0, ampl=1, orig_origin=None,
                                   orig_scale_factor=1, check_scale_factor=99):
    if check_scale_factor % 2 == 0:
        raise Exception("For this aliasing check to work, the check_scale_factor must be odd!")
    if orig_origin is None:
        origin = None
    else:
        # this preserves origin's shape, regardless of whether it's an iterable or a scalar
        origin = np.array(orig_origin) * check_scale_factor - (check_scale_factor - 1)/2
    return log_polar_grating(orig_size*check_scale_factor, alpha, w_r, w_a, phi, ampl, origin,
                             orig_scale_factor*check_scale_factor)


def aliasing_plot(better_sampled_stim, stim, slices_to_check=None, axes=None, **kwargs):
    """Plot to to check aliasing.

    This does not create the stimuli, only plots them (see `check_aliasing` or `check_aliasing_with
    mask` for functions that create the stimuli and then call this to plot them)

    to add to an existing figure, pass axes (else a new one will be created)
    """
    size = stim.shape[0]
    check_scale_factor = better_sampled_stim.shape[0] / size
    if slices_to_check is None:
        slices_to_check = [(size+1)/2]
    elif not hasattr(slices_to_check, '__iter__'):
        slices_to_check = [slices_to_check]
    if axes is None:
        fig, axes = plt.subplots(ncols=len(slices_to_check), squeeze=False,
                                 figsize=(5*len(slices_to_check), 5), **kwargs)
        # with squeeze=False, this will always be a 2d array, but because we only set ncols, it
        # will only have axes in one dimension
        axes = axes[0]
    x0 = np.array(range(size)) / float(size) + 1./(size*2)
    x1 = np.array(range(better_sampled_stim.shape[0])) / float(better_sampled_stim.shape[0]) + 1./(better_sampled_stim.shape[0]*2)
    for i, ax in enumerate(axes):
        ax.plot(x1, better_sampled_stim[:, check_scale_factor*slices_to_check[i] + (check_scale_factor - 1)/2])
        ax.plot(x0, stim[:, slices_to_check[i]], 'o:')


def check_aliasing(size, alpha, w_r=0, w_a=0, phi=0, ampl=1, origin=None, scale_factor=1,
                   slices_to_check=None, check_scale_factor=99):
    """Create a simple plot to visualize aliasing

    arguments are mostly the same as for log_polar_grating. this creates both the specified
    stimulus, `orig_stim`, and a `better_sampled_stim`, which has `check_scale_factor` more points
    in each direction. both gratings are returned and a quick plot is generated.

    NOTE that because this requires creating a much larger gradient, it can take a while. Reduce
    `check_scale_factor` to speed it up (at the risk of your "ground truth" becoming aliased)

    slices_to_check: list, None, or int. slices of the stimulus to plot. if None, will plot
    center
    """
    orig_stim = log_polar_grating(size, alpha, w_r, w_a, phi, ampl, origin, scale_factor)
    better_sampled_stim = _create_better_sampled_grating(size, alpha, w_r, w_a, phi, ampl, origin,
                                                         scale_factor, check_scale_factor)
    aliasing_plot(better_sampled_stim, orig_stim, slices_to_check)
    return orig_stim, better_sampled_stim


def _fade_mask(mask, inner_number_of_fade_pixels, outer_number_of_fade_pixels, origin=None):
    """note that mask must contain 0s where you want to mask out, 1s elsewhere
    """
    # if there's no False in mask, then we don't need to mask anything out. and if there's only
    # False, we don't need to fade anything. and if there's no fade pixels, then we don't fade
    # anything
    if False not in mask or True not in mask or (inner_number_of_fade_pixels == 0 and outer_number_of_fade_pixels == 0):
        return mask
    size = mask.shape[0]
    rad = ppt.mkR(size, origin=origin)
    inner_rad = (mask*rad)[(mask*rad).nonzero()].min()
    # in this case, there really isn't an inner radius, just an outer one, so we ignore this
    if inner_rad == rad.min():
        inner_rad = 0
        inner_number_of_fade_pixels = 0
    outer_rad = (mask*rad).max()

    # in order to get the right number of pixels to act as transition, we set the frequency based
    # on the specified number_of_fade_pixels
    def inner_fade(x):
        if inner_number_of_fade_pixels == 0:
            return (-np.cos(2*np.pi*(x-inner_rad) / (size/2.))+1)/2
        inner_fade_freq = (size/2.) / (2*inner_number_of_fade_pixels)
        return (-np.cos(inner_fade_freq*2*np.pi*(x-inner_rad) / (size/2.))+1)/2

    def outer_fade(x):
        if outer_number_of_fade_pixels == 0:
            return (-np.cos(2*np.pi*(x-outer_rad) / (size/2.))+1)/2
        outer_fade_freq = (size/2.) / (2*outer_number_of_fade_pixels)
        return (-np.cos(outer_fade_freq*2*np.pi*(x-outer_rad) / (size/2.))+1)/2

    faded_mask = np.piecewise(rad,
                              [rad < inner_rad,
                               (rad >= inner_rad) & (rad <= (inner_rad + inner_number_of_fade_pixels)),
                               (rad > (inner_rad + inner_number_of_fade_pixels)) & (rad < outer_rad - outer_number_of_fade_pixels),
                               (rad >= outer_rad - outer_number_of_fade_pixels) & (rad <= (outer_rad)),
                               (rad > (outer_rad))],
                              [0, inner_fade, 1, outer_fade, 0])
    return faded_mask


def create_sf_maps_cpp(size, alpha, w_r=0, w_a=0, origin=None, scale_factor=1):
    """Create maps of spatial frequency in cycles per pixel.

    returns two maps: the angular spatial frequency map and the radial one.
    """
    assert not hasattr(size, '__iter__'), "Only square images permitted, size must be a scalar!"
    rad = ppt.mkR(size, origin=origin)/scale_factor
    # if the origin is set such that it lies directly on a pixel, then one of the pixels will have
    # distance 0 and that means we'll have a divide by zero coming up. this little hack avoids that
    # issue.
    if 0 in rad:
        rad += 1e-12
    # the angular spatial frequency drops by 1/r as you move away from the origin, where r is the
    # distance to the origin
    a_sfmap = w_a / rad
    # the logRadial spatial frequency drops by r/(r^2+alpha^2). this is proportional to d/dr
    # log(r^2 + alpha^2)
    r_sfmap = w_r * rad / (rad**2 + alpha**2)
    # in both cases above, we don't scale the spatial frequency map appropriately (the derivative
    # of log(r) is only 1/r when the log's base is e; here it's 2 so we need to scale it). this
    # scaling constant was found experimentally; it's the value required to get the a_sfmap created
    # from log_polar_grating(8, 0, w_a=2, phase=45) to have values of .5 in the center four voxels
    # (if you create this grating, you'll be able to clearly see the center four pixels go from 1
    # to -1 to 1 to -1 and thus is at the limit of aliasing).
    a_sfmap *= (.5/2.82842712)
    r_sfmap *= (.5/2.82842712)
    return a_sfmap, r_sfmap


def create_sf_maps_cpd(size, alpha, max_visual_angle, w_r=0, w_a=0, origin=None, scale_factor=1):
    """Create maps of the spatial frequency in cycles per degree of visual angle

    returns two maps: the angular spatial frequency map and the radial one.

    Parameters
    ============

    max_visual_angle: int, the visual angle (in degrees) corresponding to the largest dimension of
    the full image (on NYU CBI's prisma scanner and the set up the Winawer lab uses, this is 28)
    """
    a_sfmap, r_sfmap = create_sf_maps_cpp(size, alpha, w_r, w_a, origin, scale_factor)
    if hasattr(size, '__iter__'):
        size = max(size)
    size = float(size)
    return a_sfmap / (max_visual_angle / size), r_sfmap / (max_visual_angle / size)


def create_antialiasing_mask(size, alpha, w_r=0, w_a=0, origin=None, number_of_fade_pixels=3, scale_factor=1):
    """Create mask to hide aliasing

    Because of how our stimuli are created, they have higher spatial frequency at the origin
    (probably center of the image) than at the edge of the image. This makes it a little harder to
    determine where aliasing will happen, which is made more complicated by the addition of alpha
    (the radius of the region where the frequency will be held constant, basically) and the
    possibility of mixing angular and logRadial frequencies. for the specified arguments, this will
    create the mask that will hide the aliasing of the grating(s) with these arguments. *NOTE* that
    this means they must have the same of all these arguments: a circular grating with this
    specified w_r and w_a=0 and a radial one with this w_a and w_r=0 need two different masks.

    the mask will not be strictly binary, there will a `number_of_fade_pixels` where it transitions
    from 0 to 1. this transition is half of a cosine.

    returns both the faded_mask and the binary mask.
    """
    a_sfmap, r_sfmap = create_sf_maps_cpp(size, alpha, w_r, w_a, origin, scale_factor)
    nyq_freq = .475
    a_mask = a_sfmap < nyq_freq
    r_mask = r_sfmap < nyq_freq
    # the two masks created above are 0 where there's aliasing and 1 everywhere else. logical_and
    # then gives us a 1 only where both have 1s; i.e., we mask out anywhere that *either* mask says
    # will alias.
    mask = np.logical_and(a_mask, r_mask)
    faded_mask = _fade_mask(mask, number_of_fade_pixels, 0, origin)
    return faded_mask, mask


def create_outer_mask(size, origin, radius=None, number_of_fade_pixels=3):
    """Create mask around the outside of the image

    this gets us a window that creates a circular (or some subset of circular) edge. this returns
    both the faded and the unfaded versions.

    radius: float or None. the radius, in pixels, of the mask. Everything farther away from the
    origin than this will be masked out. If None, we pick radius such that it's the distance to the
    edge of the square image. If horizontal and vertical have different distances, we will take the
    shorter of the two. If the distance from the origin to the horizontal edge is not identical in
    both directions, we'll take the longer of the two (similar for vertical).

    To combine this with the antialiasing mask, call np.logical_and on the two unfaded masks (and
    then fade that if you want to fade it)
    """
    rad = ppt.mkR(size, origin=origin)
    assert not hasattr(size, "__iter__"), "size must be a scalar!"
    if radius is None:
        radius = min(rad[:, size/2].max(), rad[size/2, :].max())
    mask = rad < radius
    return _fade_mask(mask, 0, number_of_fade_pixels, origin), mask


def check_aliasing_with_mask(size, alpha, w_r=0, w_a=0, phi=0, ampl=1, origin=None, scale_factor=1,
                             number_of_fade_pixels=3, slices_to_check=None):
    """check the aliasing when mask is applied
    """
    stim = log_polar_grating(size, alpha, w_r, w_a, phi, ampl, origin, scale_factor)
    fmask, mask = create_antialiasing_mask(size, alpha, w_r, w_a, origin)
    better_sampled_stim = _create_better_sampled_grating(size, alpha, w_r, w_a, phi, ampl, origin,
                                                         scale_factor, 99)
    big_fmask = fmask.repeat(99, 0).repeat(99, 1)
    big_mask = mask.repeat(99, 0).repeat(99, 1)
    if slices_to_check is None:
        slices_to_check = [(size+1)/2]
    fig, axes = plt.subplots(ncols=3, nrows=len(slices_to_check), squeeze=False,
                             figsize=(15, 5*len(slices_to_check)))
    aliasing_plot(better_sampled_stim, stim, slices_to_check, axes[:, 0])
    aliasing_plot(big_fmask*better_sampled_stim, fmask*stim, slices_to_check, axes[:, 1])
    aliasing_plot(big_mask*better_sampled_stim, mask*stim, slices_to_check, axes[:, 2])
    axes[0, 0].set_title("Slices of un-masked stimulus")
    axes[0, 1].set_title("Slices of fade-masked stimulus")
    axes[0, 2].set_title("Slices of binary-masked stimulus")
    return stim, fmask, mask, better_sampled_stim, big_fmask, big_mask


def check_stim_properties(size, origin, max_visual_angle, alpha=0, w_r=0, w_a=range(10)):
    """Creates a dataframe with data on several stimulus properties, based on the specified arguments

    the properties examined are:
    - mask radius (in pixels)
    - max frequency in cycles per pixel
    - min frequency in cycles per pixel
    - max frequency in cycles per degree
    - min frequency in cycles per degree
    - max masked frequency in cycles per pixel
    - max masked frequency in cycles per degree

    WARNING: THE CALCULATIONS FOR MIN (and possibly min) FREQUENCIES DISPLAYED IS BROKEN. I NEED TO
    THINK MORE ABOUT HOW THE MULTIPLE MAPS INTERACT WITH EACH OTHER

    note that we don't calculate the min masked frequency because that will always be zero (because
    we zero out the center of the image, where the frequency is at its highest).

    note that size, origin, and max_visual_angle must have only one value, the others can be lists
    or single values (and all combinations of them will be checked)
    """
    if hasattr(size, '__iter__'):
        raise Exception("size must *not* be iterable! All generated stimuli must be the same size")
    if hasattr(origin, '__iter__'):
        raise Exception("only one value of origin at a time!")
    if hasattr(max_visual_angle, '__iter__'):
        raise Exception("only one value of max_visual_angle at a time!")
    if not hasattr(alpha, '__iter__'):
        alpha = [alpha]
    if not hasattr(w_r, '__iter__'):
        w_r = [w_r]
    if not hasattr(w_a, '__iter__'):
        w_a = [w_a]
    rad = ppt.mkR(size, origin=origin)
    mask_df = []
    for i, (a, f_r, f_a) in enumerate(itertools.product(alpha, w_r, w_a)):
        fmask, mask = create_antialiasing_mask(size, a, f_r, f_a, origin, 0)
        a_sfmap_cpp, r_sfmap_cpp = create_sf_maps_cpp(size, a, f_r, f_a, origin)
        a_sfmap_cpd, r_sfmap_cpd = create_sf_maps_cpd(size, a, max_visual_angle, f_r, f_a, origin)
        data = {'mask_radius': (~mask*rad).max(), 'w_r': f_r, 'w_a': f_a, 'alpha': a, }
        for name, (a_sfmap, r_sfmap) in zip(['cpp', 'cpd'],
                                            [(a_sfmap_cpp, r_sfmap_cpp), (a_sfmap_cpd, r_sfmap_cpd)]):
            data[name + "_max"] = max(a_sfmap.max(), r_sfmap.max())
            data[name + "_min"] = max(a_sfmap.min(), r_sfmap.min())
            data[name + "_masked_max"] = max((fmask*a_sfmap).max(), (fmask*r_sfmap).max())
        mask_df.append(pd.DataFrame(data, index=[i]))
    return pd.concat(mask_df)


def _set_ticklabels(datashape):
    xticklabels = datashape[1]/10
    if xticklabels == 0 or xticklabels == 1:
        xticklabels = True
    yticklabels = datashape[0]/10
    if yticklabels == 0 or yticklabels == 1:
        yticklabels = True
    return xticklabels, yticklabels


def plot_stim_properties(mask_df, x='w_a', y='w_r', col='alpha', data_label='mask_radius',
                         title_text="Mask radius in pixels",
                         fancy_labels={"w_a": r"$\omega_a$", "w_r": r"$\omega_r$",
                                       "alpha": r"$\alpha$"},
                         **kwargs):
    """plot the mask_df created by check_mask_radius, to visualize how mask radius depends on args.

    fancy_labels is a dict of mask_df columns to nice (latex) ways of labeling them on the plot.
    """
    def facet_heatmap(x, y, data_label, **kwargs):
        data = kwargs.pop('data').pivot(y, x, data_label)
        xticks, yticks = _set_ticklabels(data.shape)
        sns.heatmap(data, xticklabels=xticks, yticklabels=yticks, **kwargs).invert_yaxis()

    cmap = kwargs.pop('cmap', 'Blues')
    font_scale = kwargs.pop('font_scale', 1.5)
    plotting_context = kwargs.pop('plotting_context', 'notebook')
    size = kwargs.pop('size', 3)
    with sns.plotting_context(plotting_context, font_scale=font_scale):
        g = sns.FacetGrid(mask_df, col=col, col_wrap=min(4, mask_df[col].nunique()), size=size)
        cbar_ax = g.fig.add_axes([.92, .3, .02, .4])
        g.map_dataframe(facet_heatmap, x, y, data_label, vmin=0,
                        vmax=mask_df[data_label].max(), cmap=cmap, cbar_ax=cbar_ax, **kwargs)
        g.fig.suptitle(title_text)
        g.fig.tight_layout(rect=[0, 0, .9, .95])
        g.set_axis_labels(fancy_labels[x], fancy_labels[y])
        g.set_titles(r"%s={col_name}" % fancy_labels[col])


def gen_stim_set(size, alpha, freqs_ra=[(0, 0)], phi=[0], ampl=[1], origin=None,
                 number_of_fade_pixels=3, combo_stimuli_type=['spiral'], filename=None,
                 bytescale=False):
    """Generate the specified set of stimuli and apply the anti-aliasing mask

    this function creates the specified stimuli, calculates what their anti-aliasing masks should
    be, and applies the largest of those masks to all stimuli. It also applies an outer mask so
    each of them is surrounded by faded, circular mask.

    Note that this function should be run *last*, after you've determined your parameters and
    checked to make sure the aliasing is taken care of.

    If you want to save the created stimuli (for running an experiment, you probably do), then set
    filename to a string (with extension .npy) and an array containing the masked stimuli will be
    saved there. It's recommended you place them within the data/stimuli directory

    Parameters
    =============

    freqs_ra: list of tuples of floats. the frequencies (radial and angular, in that order) of the
    stimuli to create. Each entry in the list corresponds to one stimuli, which will use the
    specified (w_r, w_a).

    combo_stimuli_type: list with possible elements {'spiral', 'plaid'}. type of stimuli to create
    when both w_r and w_a are nonzero, as described in the docstring for log_polar_grating (to
    create circular and radial stimuli, just include 0 in w_a or w_r, respectively).

    bytescale: boolean, default False. if True, calls smisc.bytescale(cmin=-ampl, cmax=ampl) on
    image to rescale it to between 0 and 255, with dtype uint8. this is done because this is
    probably sufficient for displays and takes up much less space.


    Returns
    =============

    masked and unmasked stimuli
    """
    # we need to make sure that size, origin, and number_of_fade_pixels are not iterable and the
    # other arguments are
    if hasattr(size, '__iter__'):
        raise Exception("size must *not* be iterable! All generated stimuli must be the same size")
    if hasattr(origin, '__iter__'):
        raise Exception("origin must *not* be iterable! All generated stimuli must have the same "
                        " origin")
    if hasattr(number_of_fade_pixels, '__iter__'):
        raise Exception("number_of_fade_pixels must *not* be iterable! It's a property of the mask"
                        " and we want to apply the same mask to all stimuli.")
    if hasattr(alpha, '__iter__'):
        raise Exception("alpha must *not* be iterable! All generated stimuli must have the same "
                        " alpha")
    # this isn't a typo: we want to make sure that freqs_ra is a list of tuples; an easy way to
    # check is to make sure the *entries* of freqs_ra are iterable
    if not hasattr(freqs_ra[0], '__iter__'):
        freqs_ra = [freqs_ra]
    if not hasattr(phi, '__iter__'):
        phi = [phi]
    if not hasattr(ampl, '__iter__'):
        ampl = [ampl]
    if not hasattr(combo_stimuli_type, '__iter__'):
        combo_stimuli_type = [combo_stimuli_type]
    stimuli = []
    masked_stimuli = []
    mask = []
    for w_r, w_a in freqs_ra:
        _, tmp_mask = create_antialiasing_mask(size, alpha, w_r, w_a, origin, number_of_fade_pixels)
        mask.append(tmp_mask)
    mask.append(create_outer_mask(size, origin, None, number_of_fade_pixels)[1])
    if len(mask) > 1:
        mask = np.logical_and.reduce(mask)
    else:
        mask = mask[0]
    mask = _fade_mask(mask, number_of_fade_pixels, number_of_fade_pixels, origin)
    for (w_r, w_a), p, A in itertools.product(freqs_ra, phi, ampl):
        if w_r == 0 and w_a == 0:
            # this is the empty stimulus
            continue
        if 0 in [w_r, w_a] or 'spiral' in combo_stimuli_type:
            tmp_stimuli = log_polar_grating(size, alpha, w_r, w_a, p, A, origin)
            if bytescale:
                masked_stimuli.append(smisc.bytescale(tmp_stimuli*mask, cmin=-A, cmax=A))
                stimuli.append(smisc.bytescale(tmp_stimuli, cmin=-A, cmax=A))
            else:
                masked_stimuli.append(tmp_stimuli*mask)
                stimuli.append(tmp_stimuli)
        if 'plaid' in combo_stimuli_type and 0 not in [w_r, w_a]:
            tmp_stimuli = (log_polar_grating(size, alpha, w_r, 0, p, A, origin) +
                           log_polar_grating(size, alpha, 0, w_a, p, A, origin))
            if bytescale:
                masked_stimuli.append(smisc.bytescale(tmp_stimuli*mask, cmin=-A, cmax=A))
                stimuli.append(smisc.bytescale(tmp_stimuli, cmin=-A, cmax=A))
            else:
                masked_stimuli.append(tmp_stimuli*mask)
                stimuli.append(tmp_stimuli)
    if filename is not None:
        if not filename.endswith('.npy'):
            warnings.warn("filename %s does not end in .npy, so adding that extension" % filename)
            filename += ".npy"
        np.save(filename, masked_stimuli)
    return masked_stimuli, stimuli


## TODO: set random seed
def main(subject_name, output_dir="../data/stimuli/", create_stim=True, create_idx=True):
    """create the stimuli for the spatial frequency preferences experiment

    Our stimuli are constructed from a 2d frequency space, with w_r on the x-axis and w_a on the
    y. The stimuli we want for our experiment then lie along the x-axis, the y-axis, the + and -
    45-degree angle lines (that is, x=y and x=-y, y>0 for both), and the arc that connects all of
    them. For those stimuli that lie along straight lines / axes, they'll have frequencies from
    2^(2.5) to 2^(7.5) (distance from the radius) in half-octave increments, while the arc will lie
    half-way between the two extremes, with radius 2^(7.5-2.5)=32. We don't use the actual
    half-octave increments, because non-integer frequencies cause obvious breaks (especially in the
    spirals), so we round all frequencies to the nearest integer.

    all stimuli will have the same alpha value, _, and there will be 8 different phases equally
    spaced from 0 to 2 pi: np.array(range(8))/8.*2*np.pi

    These will be arranged into blocks of 8 so that each stimuli within one block differ only by
    their phase. We will take this set of stimuli and randomize it, within and across those blocks,
    to create 12 different orders, for the 12 different runs per scanning session. There will also
    be 10 blank trials per session, pseudo-randomly interspersed (these will be represented as
    arrays full of 0s; there will never be two blank trials in a row).

    The actual stimuli will be saved as unshuffled.npy in the output_dir, while the indices
    necessary to shuffle it will be saved at {subj}_run_00_idx.npy through {subj}_run_11_idx.npy. A
    description of the stimuli properties, in the order found in unshuffled, is saved at
    unshuffled_stim_description.csv in the output folder, as a pandas DataFrame. In order to view
    the properties of a shuffled one, load that DataFrame in as df, and the index as idx, then call
    df.iloc[idx]

    if create_stim is False, then we don't create the stim, just create and save the shuffled
    indices.

    NOTE That if create_idx is True and the indices already exist, this will throw an
    exception. Similarly if create_stim is True and either the stimuli .npy file or the descriptive
    dataframe .csv file

    returns (one copy) of the (un-shuffled) stimuli, for inspection.
    """
    if output_dir[-1] != '/':
        output_dir += '/'
    filename = output_dir + "{subj}_run%02d_idx.npy".format(subj=subject_name)
    nruns = 12
    num_blank_trials = 10
    alpha = 50
    base_freqs = [2**i for i in np.arange(2.5, 8, .5)]
    # circular, where w_r=0
    freqs = [(0, f) for f in base_freqs]
    # radial, where w_a=0
    freqs.extend([(f, 0) for f in base_freqs])
    # spirals, where w_a=w_r or -w_a=w_r
    freqs.extend([(f*np.sin(np.pi/4), f*np.sin(np.pi/4)) for f in base_freqs])
    freqs.extend([(-f*np.sin(np.pi/4), f*np.sin(np.pi/4)) for f in base_freqs])
    # arc, where distance from the origin is 2^5
    #  skip those values which we've already gotten: 0, pi/4, pi/2, 3*pi/4, and pi
    angles = [np.pi*1/12.*i for i in [1, 2, 4, 5, 7, 8, 10, 11]]
    freqs.extend([(base_freqs[len(base_freqs)/2]*np.sin(i),
                   base_freqs[len(base_freqs)/2]*np.cos(i)) for i in angles])
    freqs = np.round(freqs)
    n_classes = len(freqs) + num_blank_trials
    n_exemplars = 8
    phi = np.array(range(n_exemplars))/float(n_exemplars)*2*np.pi
    res = 1080
    if create_idx:
        if os.path.isfile(filename % 0):
            raise Exception("Indices with template %s already exist!" % filename)
        for i in range(nruns):
            class_idx = np.array(range(n_classes))
            # we don't want to have two blank trials in a row, so we use this little method to
            # avoid that. blank_idx contains the class indices that correspond to blanks, e.g., the
            # last 10 of them
            blank_idx = class_idx.copy()[-num_blank_trials:]
            # this is where they are in the current class_idx
            blank_loc = np.where(np.in1d(class_idx, blank_idx))[0]
            # now, if two blanks are next to each other, this will return true and thus we shuffle
            # class_idx. note that this will always return true the first time, which is good
            # because we want at least one shuffle. This is the "dumb way" of doing this, which
            # relies *heavily* on the fact that there aren't many blank trials relative to the
            # total number of classes.
            while 1 in (blank_loc[1:] - blank_loc[:-1]):
                np.random.shuffle(class_idx)
                blank_loc = np.where(np.in1d(class_idx, blank_idx))[0]
            class_idx = np.repeat(class_idx * n_exemplars, n_exemplars)
            ex_idx = []
            for j in range(n_classes):
                ex_idx_tmp = np.array(range(n_exemplars))
                np.random.shuffle(ex_idx_tmp)
                ex_idx.extend(ex_idx_tmp)
            np.save(filename % i, class_idx + ex_idx)
    if create_stim:
        if os.path.isfile(output_dir + "unshuffled.npy"):
            raise Exception("unshuffled data already exists!")
        if os.path.isfile(output_dir + "unshuffled_stim_description.csv"):
            raise Exception("unshuffled data already exists!")
        stim, _ = gen_stim_set(res, alpha, freqs, phi, bytescale=True)
        stim = np.concatenate([np.array(stim),
                               smisc.bytescale(np.zeros((num_blank_trials * n_exemplars, res, res)),
                                               cmin=-1, cmax=1)])
        np.save(output_dir + "unshuffled.npy", stim)
        df = []
        for i, ((w_r, w_a), p) in enumerate(itertools.product(freqs, phi)):
            df.append((w_r, w_a, p, res, alpha, i))
        max_idx = i+1
        for i, _ in enumerate(itertools.product(range(num_blank_trials), phi)):
            df.append((None, None, None, res, None, i+max_idx))
        df = pd.DataFrame(df, columns=['w_r', 'w_a', 'phi', 'res', 'alpha', 'index'])
        df.to_csv(output_dir + "unshuffled_stim_description.csv")
        return stim


if __name__ == '__main__':
    class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass
    parser = argparse.ArgumentParser(description=(main.__doc__),
                                     formatter_class=CustomFormatter)
    parser.add_argument("subject_name", help=("The name of the subject for this randomization. "
                        "Will be used in filename for data."))
    parser.add_argument("--output_dir", '-o', help="directory to place stimuli and indices in",
                        default="data/stimuli")
    parser.add_argument("--create_stim", '-c', action="store_true",
                        help="Create and save the experiment stimuli and descriptive dataframe")
    parser.add_argument("--create_idx", '-i', action="store_true",
                        help=("Create and save the 12 randomized indices for this subject"))
    args = vars(parser.parse_args())
    if not args["create_stim"] and not args['create_idx']:
        print("Nothing to create, exiting...")
    else:
        _ = main(**args)
