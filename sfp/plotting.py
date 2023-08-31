#!/usr/bin/python
"""high-level functions to make relevant plots
"""
import matplotlib as mpl
# we do this because sometimes we run this without an X-server, and this backend doesn't need
# one. We set warn=False because the notebook uses a different backend and will spout out a big
# warning to that effect; that's unnecessarily alarming, so we hide it.
import argparse
import itertools
from . import utils
import warnings
import os
from . import tuning_curves
from . import stimuli as sfp_stimuli
from . import model as sfp_model
from . import first_level_analysis
from . import analyze_model
import numpy as np
import seaborn as sns
import neuropythy as ny
import matplotlib.pyplot as plt
import pandas as pd
import scipy as sp
from sklearn import linear_model

LOGPOLAR_SUPERCLASS_ORDER = ['radial', 'forward spiral', 'angular', 'reverse spiral', 'mixtures', 'baseline']
CONSTANT_SUPERCLASS_ORDER = ['vertical', 'forward diagonal', 'horizontal', 'reverse diagonal',
                             'off-diagonal']
# radial and angular are ambiguous labels -- do they refer to the direction of
# the oscillation or the stripes? annulus and pinwheel are less ambiguous in
# this regard, so we use them in the paper.
SUPERCLASS_PLOT_LABELS = {'radial': 'annulus', 'angular': 'pinwheel', 'baseline': 'blank'}
ORIG_PARAM_ORDER = (['sigma', 'sf_ecc_slope', 'sf_ecc_intercept'] +
                    ['%s_%s_%s' % (i, j, k) for j, i, k in
                     itertools.product(['mode', 'amplitude'], ['abs', 'rel'],
                                       ['cardinals', 'obliques'])])
PLOT_PARAM_ORDER = [r'$\sigma$', r'$a$', r'$b$', r'$p_1$', r'$p_2$', r'$p_3$', r'$p_4$', r'$A_1$',
                    r'$A_2$', r'$A_3$', r'$A_4$']
MODEL_ORDER = ['constant_donut_period-iso_amps-iso', 'scaling_donut_period-iso_amps-iso',
               'full_donut_period-iso_amps-iso', 'full_donut_period-absolute_amps-iso',
               'full_donut_period-relative_amps-iso', 'full_donut_period-full_amps-iso',
               'full_donut_period-iso_amps-absolute', 'full_donut_period-iso_amps-relative',
               'full_donut_period-iso_amps-full', 'full_donut_period-absolute_amps-absolute',
               'full_donut_period-relative_amps-relative', 'full_donut_period-full_amps-absolute',
               'full_donut_period-full_amps-relative', 'full_donut_period-full_amps-full']
# these are the 'prettier names' for plotting
MODEL_PLOT_ORDER_FULL = (['constant iso', 'scaling iso', 'full iso'] +
                         [i.replace('_donut', '').replace('_', ' ') for i in MODEL_ORDER[3:]])
# using the numbers instead of names, since names aren't that helpful
MODEL_PLOT_ORDER = list(range(1, len(MODEL_ORDER)+1))
# "doubles-up" the model types, so that numbers are unique for parameters
# excluding A3/A4 (so if two models have the same number, they're identical
# except for those two parameters)
MODEL_PLOT_ORDER_DOUBLEUP = MODEL_PLOT_ORDER[:7] + [3, 7, 10, 5, 12, 6, 12]
# the subjects that end up in our final analysis
SUBJECT_ORDER = ['sub-wlsubj001', 'sub-wlsubj006', 'sub-wlsubj007', 'sub-wlsubj045',
                 'sub-wlsubj046', 'sub-wlsubj062', 'sub-wlsubj064', 'sub-wlsubj081',
                 'sub-wlsubj095', 'sub-wlsubj114', 'sub-wlsubj115', 'sub-wlsubj121']
# use numbers since names aren't helpful for plots
SUBJECT_PLOT_ORDER = [f'sub-{i:02d}' for i in range(1, len(SUBJECT_ORDER)+1)]


def get_order(col, reference_frame=None, col_unique=None):
    """get order for column
    """
    if col == 'stimulus_type':
        return stimulus_type_order(reference_frame)
    elif col == 'fit_model_type':
        if any([i in col_unique for i in MODEL_PLOT_ORDER]):
            return [i for i in MODEL_PLOT_ORDER if i in col_unique]
        elif any([i in col_unique for i in MODEL_PLOT_ORDER_FULL]):
            return [i for i in MODEL_PLOT_ORDER_FULL if i in col_unique]
        else:
            return [i for i in MODEL_ORDER if i in col_unique]
    elif col == 'model_parameter':
        if col_unique is not None and 'sigma' in col_unique:
            return ORIG_PARAM_ORDER
        else:
            return PLOT_PARAM_ORDER
    elif col == 'subject':
        if col_unique is None:
            return SUBJECT_PLOT_ORDER
        elif any([sub in col_unique for sub in SUBJECT_PLOT_ORDER]):
            return [sub for sub in SUBJECT_PLOT_ORDER if sub in col_unique]
        elif any([sub in col_unique for sub in SUBJECT_ORDER]):
            return [sub for sub in SUBJECT_ORDER if sub in col_unique]
    else:
        return sorted(col_unique)


def get_palette(col, reference_frame=None, col_unique=None, as_dict=False,
                doubleup=False):
    """get palette for column

    Parameters
    ----------
    col : {'stimulus_type', 'subject', 'fit_model_type', 'model_parameter'}
        The column to return the palette for
    reference_frame : {'absolute', 'relative', None}, optional
        The reference frame (ignored if col!='stimulus_type')
    col_unique : list or None, optional
        The list of unique values in col, in order to determine how many
        elements in the palette. If None, we use seaborn's default
    as_dict : bool, optional
        Whether to return the palette as a dictionary or not. if True, then we
        also find the order for this column (using get_order), and return a
        dictionary matching between the elements of this col and the colors in
        the palette (this can still be passed as the palette argument to most
        seaborn plots).
    doubleup: bool, optional
        Whether to return the doubleup palette for fit_model_type (8 unique
        colors and then 6 versions with lower alpha). Ignored if
        col!='fit_model_type'

    """
    if col == 'stimulus_type':
        pal = stimulus_type_palette(reference_frame)
        pal = dict((k, v) for k, v in pal.items() if k in col_unique)
        if not as_dict:
            raise Exception("palette is always a dictionary if col is stimulus_type!")
    elif col == 'subject':
        # it's hard to find a qualitative color palette with 12 colors that all
        # look fairly distinct. ColorBrewer Set3 has 12 values, but some of
        # them are really light and so hard to see. here I'm using the colors
        # from https://tsitsul.in/blog/coloropt/, but reordered slightly
        pal = [(235, 172, 35), (0, 187, 173), (184, 0, 88), (0, 140, 249),
               (0, 110, 0), (209, 99, 230), (178, 69, 2), (135, 133, 0),
               (89, 84, 214), (255, 146, 135), (0, 198, 248), (0, 167, 108),
               (189, 189, 189)]
        # expects RGB triplets to lie between 0 and 1, not 0 and 255
        pal = sns.color_palette(np.array(pal) / 255, len(col_unique))
    elif col == 'fit_model_type':
        if not doubleup:
            pal = sns.color_palette('deep', len(col_unique))
        else:
            if len(col_unique) != len(MODEL_PLOT_ORDER):
                raise Exception("Can only return doubleup model type palette "
                                "if plotting all models!")
            # can't set the alpha channel of palettes for seaborn functions, so
            # we use this workaround. fortunately, we only need 5 pairs of
            # colors, because that's all that Paired contains!
            pal = np.concatenate([sns.color_palette('Paired', 10),
                                  sns.color_palette('deep')[-5:-1]])
            pal = pal[[-1, -2, 1, -3, 3, 5, 7, 0, 6, -4, 2, 9, 4, 8]]
    elif col == 'model_parameter':
        # I don't think we actually need distinct colors for model parameter,
        # so we plot them all black
        pal = ['k'] * len(col_unique)
    elif col == 'freq_space_distance':
        pal = sns.color_palette('gray', len(col_unique))
    else:
        pal = sns.color_palette('Blues', len(col_unique))
    # if col=='stimulus_type', this is already a dict
    if as_dict and col != 'stimulus_type':
        order = get_order(col, reference_frame, col_unique)
        pal = dict(zip(order, pal))
    return pal


def stimulus_type_palette(reference_frame):
    palette = {}
    if isinstance(reference_frame, str):
        reference_frame = [reference_frame]
    if 'relative' in reference_frame:
        # the last one is midgray for blanks
        pal = sns.color_palette('deep', 5) + [(.5, .5, .5)]
        palette.update(dict(zip(LOGPOLAR_SUPERCLASS_ORDER, pal)))
    if 'absolute' in reference_frame:
        pal = sns.color_palette('cubehelix', 5)
        palette.update(dict(zip(CONSTANT_SUPERCLASS_ORDER, pal)))
    return palette


def stimulus_type_order(reference_frame):
    order = []
    if isinstance(reference_frame, str):
        reference_frame = [reference_frame]
    for t in reference_frame:
        order.extend({'relative': LOGPOLAR_SUPERCLASS_ORDER,
                      'absolute': CONSTANT_SUPERCLASS_ORDER}[t])
    return order


def is_numeric(s):
    """check whether data s is numeric

    s should be something that can be converted to an array: list,
    Series, array, column from a DataFrame, etc

    this is based on the function
    seaborn.categorical._CategoricalPlotter.infer_orient.is_not_numeric

    Parameters
    ----------
    s :
        data to check

    Returns
    -------
    is_numeric : bool
        whether s is numeric or not
    """
    try:
        np.asarray(s, dtype=np.float)
    except ValueError:
        return False
    return True


def draw_arrow(ax, xy, xytext, text="", arrowprops={}, **kwargs):
    kwargs.setdefault('xycoords', 'data')
    kwargs.setdefault('textcoords', 'data')
    ax.annotate(text, xy=xy, xytext=xytext, arrowprops=arrowprops, **kwargs)


class MidpointNormalize(mpl.colors.Normalize):
    def __init__(self, vmin=None, vmax=None, midpoint=None, clip=False):
        self.midpoint = midpoint
        mpl.colors.Normalize.__init__(self, vmin, vmax, clip)

    def __call__(self, value, clip=None):
        # I'm ignoring masked values and all kinds of edge cases to make a
        # simple example...
        x, y = [self.vmin, self.midpoint, self.vmax], [0, 0.5, 1]
        return np.ma.masked_array(np.interp(value, x, y))


def myLogFormat(y, pos):
    """formatter that only shows the required number of decimal points

    this is for use with log-scaled axes, and so assumes that everything greater than 1 is an
    integer and so has no decimal points

    to use (or equivalently, with `axis.xaxis`):
    ```
    from matplotlib import ticker
    axis.yaxis.set_major_formatter(ticker.FuncFormatter(myLogFormat))
    ```

    modified from https://stackoverflow.com/a/33213196/4659293
    """
    # Find the number of decimal places required
    if y < 1:
        # because the string representation of a float always starts "0."
        decimalplaces = len(str(y)) - 2
    else:
        decimalplaces = 0
    # Insert that number into a format string
    formatstring = '{{:.{:1d}f}}'.format(decimalplaces)
    # Return the formatted tick label
    return formatstring.format(y)


def _jitter_data(data, jitter):
    """optionally jitter data some amount

    jitter can be None / False (in which case no jittering is done), a number (in which case we add
    uniform noise with a min of -jitter, max of jitter), or True (in which case we do the uniform
    thing with min/max of -.1/.1)

    based on seaborn.linearmodels._RegressionPlotter.scatter_data
    """
    if jitter is None or jitter is False:
        return data
    else:
        if jitter is True:
            jitter = .1
        return data + np.random.uniform(-jitter, jitter, len(data))


def im_plot(im, **kwargs):
    try:
        cmap = kwargs.pop('cmap')
    except KeyError:
        cmap = 'gray'
    try:
        ax = kwargs.pop('ax')
        ax.imshow(im, cmap=cmap, **kwargs)
    except KeyError:
        ax = plt.imshow(im, cmap=cmap, **kwargs)
    ax.axes.xaxis.set_visible(False)
    ax.axes.yaxis.set_visible(False)


def plot_median(x, y, plot_func=plt.plot, **kwargs):
    """plot the median points, for use with seaborn's map_dataframe

    plot_func specifies what plotting function to call on the median points (e.g., plt.plot,
    plt.scatter)
    """
    data = kwargs.pop('data')
    x_data, plot_data, _, _ = _map_dataframe_prep(data, x, y, np.median, None, None, None, 68)
    plot_func(x_data, plot_data.values, **kwargs)


def plot_ci(x, y, ci_vals=[16, 84], **kwargs):
    """fill between the specified CIs, for use with seaborn's map_dataframe
    """
    data = kwargs.pop('data')
    alpha = kwargs.pop('alpha', .2)
    plot_data = data.groupby(x)[y].apply(np.percentile, ci_vals)
    plot_values = np.vstack(plot_data.values)
    plt.fill_between(plot_data.index, plot_values[:, 0], plot_values[:, 1], alpha=alpha, **kwargs)


def scatter_ci_col(x, y, ci, x_order=None, x_jitter=None, **kwargs):
    """plot center points and specified CIs, for use with seaborn's map_dataframe

    based on seaborn.linearmodels.scatterplot. CIs are taken from a column in this function.
    """
    data = kwargs.pop('data')
    ax = plt.gca()
    plot_data = data.groupby(x)[y].median()
    plot_cis = data.groupby(x)[ci].median()
    if x_order is not None:
        plot_data = plot_data.reindex(x_order)
        plot_cis = plot_cis.reindex(x_order)
    for i, ((x_data, group_data), (_, group_cis)) in enumerate(zip(plot_data.items(), plot_cis.items())):
        try:
            x_data = _jitter_data(x_data, x_jitter)
        except TypeError:
            x_data = np.ones(1) * i
            x_data = _jitter_data(x_data, x_jitter)
        ax.scatter(x_data, group_data, **kwargs)
        ax.plot([x_data, x_data], [group_data+group_cis, group_data-group_cis], **kwargs)
    ax.set(xticks=range(len(plot_data)), xticklabels=plot_data.index.values)


def _map_dataframe_prep(data, x, y, estimator, x_jitter, x_dodge, x_order, ci=68):
    """prepare dataframe for plotting

    Several of the plotting functions are called by map_dataframe and
    need a bit of prep work before plotting. These include:
    - computing the central trend
    - computing the CIs
    - jittering, dodging, or ordering the x values

    Parameters
    ----------
    data : pd.DataFrame
        The dataframe containing the info to plot
    x : str
        which column of data to plot on the x-axis
    y : str
        which column of data to plot on the y-axis
    estimator : callable, optional
        what function to use for estimating central trend of the data
    x_jitter : float, bool, or None, optional
        whether to jitter the data along the x-axis. if None or False,
        don't jitter. if a float, add uniform noise (drawn from
        -x_jitter to x_jitter) to each point's x value. if True, act as
        if x_jitter=.1
    x_dodge : float, None, or bool, optional
        to improve visibility with many points that have the same
        x-values (or are categorical), we can jitter the data along the
        x-axis, but we can also "dodge" it, which operates
        deterministically. x_dodge should be either a single float or an
        array of the same shape as x (we will dodge by calling `x_data =
        x_data + x_dodge`). if None, we don't dodge at all. If True, we
        dodge as if x_dodge=.01
    x_order: np.array or None, optional
        the order to plot x-values in. If None, don't reorder
    ci : int, optinoal
        The width fo the CI to draw (in percentiles)

    Returns
    -------
    x_data : np.array
        the x data to plot
    plot_data : np.array
        the y data of the central trend
    plot_cis : np.array
        the y data of the CIs
    x_numeric : bool
        whether the x data is numeric or not (used to determine if/how
        we should update the x-ticks)

    """
    plot_data = data.groupby(x)[y].agg(estimator)
    ci_vals = [50 - ci/2, 50 + ci/2]
    plot_cis = [data.groupby(x)[y].agg(np.percentile, val) for val in ci_vals]
    if x_order is not None:
        plot_data = plot_data.reindex(x_order)
        plot_cis = [p.reindex(x_order) for p in plot_cis]
    x_data = plot_data.index
    # we have to check here because below we'll end up making things
    # numeric
    x_numeric = is_numeric(x_data)
    if not x_numeric:
        x_data = np.arange(len(x_data))
    x_data = _jitter_data(x_data, x_jitter)
    # at this point, x_data could be an array or the index of a
    # dataframe. we want it to be an array for all the following calls,
    # and this try/except forces that
    try:
        x_data = x_data.values
    except AttributeError:
        pass
    if x_dodge is not None:
        if x_dodge is True:
            x_dodge = .01
        x_data = x_data + x_dodge
    return x_data, plot_data, plot_cis, x_numeric


def scatter_ci_dist(x, y, ci=68, x_jitter=None, join=False, estimator=np.median,
                    draw_ctr_pts=True, ci_mode='lines', ci_alpha=.2, size=5, x_dodge=None,
                    **kwargs):
    """plot center points and specified CIs, for use with seaborn's map_dataframe

    based on seaborn.linearmodels.scatterplot. CIs are taken from a
    distribution in this function. Therefore, it's assumed that the
    values being passed to it are values from a bootstrap distribution.

    by default, this draws the 68% confidence interval. to change this,
    change the ci argument. for instance, if you only want to draw the
    estimator point, pass ci=0

    Parameters
    ----------
    x : str
        which column of data to plot on the x-axis
    y : str
        which column of data to plot on the y-axis
    ci : int, optinoal
        The width fo the CI to draw (in percentiles)
    x_jitter : float, bool, or None, optional
        whether to jitter the data along the x-axis. if None or False,
        don't jitter. if a float, add uniform noise (drawn from
        -x_jitter to x_jitter) to each point's x value. if True, act as
        if x_jitter=.1
    join : bool, optional
        whether to connect the central trend of the data with a line or
        not.
    estimator : callable, optional
        what function to use for estimating central trend of the data,
        as plotted if either draw_ctr_pts or join is True.
    draw_ctr_pts : bool, optional
        whether to draw the center points (as given by estimator).
    ci_mode : {'lines', 'fill'}, optional
        how to draw the CI. If 'lines', we draw lines for the CI. If
        'fill', we shade the region of the CI, with alpha given by
        ci_alpha
    ci_alpha : float, optional
        the alpha value for the CI, if ci_mode=='fill'
    size : float, optional
        Diameter of the markers, in points. (Although plt.scatter is
        used to draw the points, the size argument here takes a "normal"
        markersize and not size^2 like plt.scatter, following how it's
        done by seaborn.stripplot).
    x_dodge : float, None, or bool, optional
        to improve visibility with many points that have the same
        x-values (or are categorical), we can jitter the data along the
        x-axis, but we can also "dodge" it, which operates
        deterministically. x_dodge should be either a single float or an
        array of the same shape as x (we will dodge by calling `x_data =
        x_data + x_dodge`). if None, we don't dodge at all. If True, we
        dodge as if x_dodge=.01
    kwargs :
        must contain data. Other expected keys:
        - ax: the axis to draw on (otherwise, we grab current axis)
        - x_order: the order to plot x-values in. Otherwise, don't
          reorder
        everything else will be passed to the scatter, plot, and
        fill_between functions called (except label, which will not be
        passed to the plot or fill_between function call that draws the
        CI, in order to make any legend created after this prettier)

    Returns
    -------
    dots, lines, cis :
        The handles for the center points, lines connecting them (if
        join=True), and CI lines/fill. this is returned for better
        control over what shows up in the legend.

    """
    data = kwargs.pop('data')
    ax = kwargs.pop('ax', plt.gca())
    x_order = kwargs.pop('x_order', None)
    x_data, plot_data, plot_cis, x_numeric = _map_dataframe_prep(data, x, y, estimator, x_jitter,
                                                                 x_dodge, x_order, ci)
    if draw_ctr_pts:
        # scatter expects s to be the size in pts**2, whereas we expect
        # size to be the diameter, so we convert that (following how
        # it's handled by seaborn's stripplot)
        dots = ax.scatter(x_data, plot_data.values, s=size**2, **kwargs)
    else:
        dots = None
    if join is True:
        lines = ax.plot(x_data, plot_data.values, **kwargs)
    else:
        lines = None
    # if we attach label to the CI, then the legend may use the CI
    # artist, which we don't want
    kwargs.pop('label', None)
    if ci_mode == 'lines':
        for x, (ci_low, ci_high) in zip(x_data, zip(*plot_cis)):
            cis = ax.plot([x, x], [ci_low, ci_high], **kwargs)
    elif ci_mode == 'fill':
        cis = ax.fill_between(x_data, plot_cis[0].values, plot_cis[1].values, alpha=ci_alpha,
                              **kwargs)
    else:
        raise Exception(f"Don't know how to handle ci_mode {ci_mode}!")
    # if we do the following when x is numeric, things get messed up.
    if (x_jitter is not None or x_dodge is not None) and not x_numeric:
        ax.set(xticks=range(len(plot_data)), xticklabels=plot_data.index.values)
    return dots, lines, cis


def plot_noise_ceiling(x, y, ci=68, x_extent=.5, estimator=np.median, ci_alpha=.2,
                       orient='v', **kwargs):
    """plot the noise ceiling

    this is similar to scatter_ci_dist except that we want to plot each
    x value as a separate line, to make it clear there's no connection
    between them, and we always show the CIs using fill.

    Parameters
    ----------
    x : str
        which column of data to plot on the x-axis
    y : str
        which column of data to plot on the y-axis
    ci : int, optinoal
        The width fo the CI to draw (in percentiles)
    x_extent : float, optional
        we want to show the noise ceiling as a flat line, so we need it
        to extend beyond the exact x-value (which would just result in a
        point). to do that, x_extent controls the size of this line; we
        plot from `x-x_extent` to `x+x_extent` for each x.
    estimator : callable, optional
        what function to use for estimating central trend of the data,
        as plotted if either draw_ctr_pts or join is True.
    ci_alpha : float, optional
        the alpha value for the CI, if ci_mode=='fill'
    orient : {'h', 'v'}, optional
        orientation of plot (horizontal or vertical)
    kwargs :
        must contain data. Other expected keys:
        - ax: the axis to draw on (otherwise, we grab current axis)
        - x_order: the order to plot x-values in. Otherwise, don't
          reorder
        everything else will be passed to the scatter, plot, and
        fill_between functions called (except label, which will not be
        passed to the plot or fill_between function call that draws the
        CI, in order to make any legend created after this prettier)

    Returns
    -------
    lines, cis :
        The handles for the lines showing the noise level and the CI
        fill. this is returned for better control over what shows up in
        the legend. all lines have `label='noise_ceiling'`, the CIs have
        no label

    """
    data = kwargs.pop('data')
    ax = kwargs.pop('ax', plt.gca())
    x_order = kwargs.pop('x_order', None)
    x_data, plot_data, plot_cis, _ = _map_dataframe_prep(data, x, y, estimator, None, None, None,
                                                         ci)
    if is_numeric(x_data):
        warnings.warn("With numeric x_data, there's a confusion between the integer values and "
                      f"the categorical labels -- we're subtracting off the min value, {min(x_data)},"
                      " to avoid this situation")
        x_data -= min(x_data)
    y_extent = 0
    # then flip everything
    if orient == 'h':
        x_tmp = x_data
        x_data = plot_data
        plot_data = x_tmp
        y_extent = x_extent
        x_extent = 0
    lines = []
    cis = []
    for x, d, ci_low, ci_high in zip(x_data, plot_data, *plot_cis):
        lines.append(ax.plot([x-x_extent, x+x_extent], [d-y_extent, d+y_extent],
                             label='noise ceiling', **kwargs))
        cis.append(ax.fill_between([x-x_extent, x+x_extent], ci_low, ci_high, alpha=ci_alpha,
                                   **kwargs))
    return lines, cis


def plot_median_fit(x, y, model=linear_model.LinearRegression(), x_vals=None, **kwargs):
    """plot a model fit to the median points, for use with seaborn's map_dataframe

    we first find the median values of y when grouped by x and then fit model to them and plot
    *only* the model's predictions (thus you'll need to call another function if you want to see
    the actual data). we don't cross-validate or do anything fancy.

    model should be an (already-initialized) class that has a fit (which accepts X and y) and a
    predict method (which accepts X; for instance, anything from sklearn). It should expect X to be
    2d; we reshape our 1d data to be 2d (since this is what the sklearn models expect)
    """
    data = kwargs.pop('data')
    if 'exclude' in kwargs['label']:
        # we don't plot anything with exclude in the label
        return
    plot_data = data.groupby(x)[y].median()
    model.fit(plot_data.index.values.reshape(-1, 1), plot_data.values)
    if x_vals is None:
        x_vals = plot_data.index
    x_vals = np.array(x_vals).reshape(-1, 1)
    plt.plot(x_vals, model.predict(x_vals), **kwargs)


def stimuli_properties(df, save_path=None):
    """plot some summaries of the stimuli properties

    this plots three pieces stimulus properties as a function of their position in frequency space
    (either w_x / w_y or w_r / w_a): superclass (radial, angular, etc / horizontal, vertical,
    etc), distance from the origin in frequency space, and angle in the frequency space. these
    various properties of the stimuli will be used to summarize results later on and so are
    important to have a handle on.

    df: pandas DataFrame containing stimulus information. should be either the stimulus description
    dataframe or the first level results dataframe.
    """
    if 'voxel' in df.columns:
        df = df[df.voxel == df.voxel.unique()[0]]
    else:
        df = df.dropna()
        df.class_idx = df.class_idx.astype(int)
        df = df.drop_duplicates('class_idx').set_index('class_idx')
        df = df.rename(columns={'index': 'stimulus_index'})
        df = first_level_analysis._add_freq_metainfo(df)
    if 'baseline' in df.stimulus_superclass.unique():
        df = df[df.stimulus_superclass != 'baseline']
    figsize = (19, 5)
    cmaps = [None, sns.cubehelix_palette(as_cmap=True),
             sns.diverging_palette(10, 220, as_cmap=True)]
    try:
        df['w_a']
        freq_names = ['w_r', 'w_a']
        if 181 in df['w_a'].unique():
            # then this is the pilot data, which goes out further in frequency space
            if df['freq_space_angle'].max() > 2:
                # then this is the first pilot, which has a bit different angles
                ylim, xlim = [-75, 200], [-150, 250]
                figsize = (20, 6)
            else:
                ylim, xlim = [-176, 212], [-28, 311]
        else:
            ylim, xlim = [-125, 150], [-20, 220]
        cmaps[0] = stimulus_type_palette('relative')
    except KeyError:
        freq_names = ['w_x', 'w_y']
        ylim, xlim = [-.098, .118], [-.0157, .173]
        cmaps[0] = stimulus_type_palette('absolute')
    norms = [None, None, MidpointNormalize(df.freq_space_angle.min(),
                                           df.freq_space_angle.max(), midpoint=0)]
    titles = ['Frequency superclass', 'Frequency distance', "Frequency angle"]
    color_prop = ['stimulus_superclass', 'freq_space_distance', 'freq_space_angle']
    with sns.axes_style('white'):
        fig, axes = plt.subplots(1, 3, figsize=figsize)
        for i, ax in enumerate(axes.flatten()):
            # zorder ensures that the lines are plotted before the points in the scatterplot
            ax.plot(xlim, [0, 0], 'k--', alpha=.5, zorder=1)
            ax.plot([0, 0], ylim, 'k--', alpha=.5, zorder=2)
            if i == 0:
                handles = []
                labels = []
                for lab, g in df.groupby(color_prop[i]):
                    pts = ax.scatter(g[freq_names[0]].values, g[freq_names[1]].values,
                                     c=cmaps[i][lab], edgecolors='k', zorder=3)
                    handles.append(pts)
                    labels.append(lab)
                ax.legend(handles, labels)
            elif 0 < i < 3:
                pts = ax.scatter(df[freq_names[0]].values, df[freq_names[1]].values,
                                 c=df[color_prop[i]].values, cmap=cmaps[i], edgecolors='k',
                                 norm=norms[i], zorder=3)
                fig.colorbar(pts, ax=ax, fraction=.046, pad=.1)
            else:
                ax.set_visible(False)
                continue
            ax.set_aspect('equal')
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
            ax.set_title(titles[i], fontsize=15)
            ax.set_xlabel("$\omega_%s$" % freq_names[0][-1], fontsize=20)
            ax.set_ylabel("$\omega_%s$" % freq_names[1][-1], fontsize=20)
    sns.despine()
    if save_path is not None:
        fig.savefig(save_path, bbox_inches='tight')
    return fig


def local_spatial_frequency(df, save_path=None, **kwargs):
    """plot the local spatial frequency for all stimuli

    df: first_level_analysis results dataframe.

    all kwargs get passed to plt.plot
    """
    if 'rounded_freq_space_distance' in df.columns:
        hue_label = 'rounded_freq_space_distance'
        col_order = LOGPOLAR_SUPERCLASS_ORDER
    else:
        hue_label = 'freq_space_distance'
        col_order = CONSTANT_SUPERCLASS_ORDER

    def mini_plot(x, y, **kwargs):
        # this function converts the stringified floats of eccentricity to floats and correctly
        # orders them for plotting.
        x = [np.mean([float(j) for j in i.split('-')]) for i in x.values]
        plot_vals = sorted(zip(x, y.values), key=lambda pair: pair[0])
        plt.plot([i for i, _ in plot_vals], [j for _, j in plot_vals], **kwargs)

    with sns.axes_style('white'):
        g = sns.FacetGrid(df, hue=hue_label, col='stimulus_superclass', palette='Reds', col_wrap=3,
                          col_order=col_order)
        g.map(mini_plot, 'eccen', 'local_sf_magnitude', **kwargs)
        g.add_legend()
        plt.subplots_adjust(top=.9)
        g.fig.suptitle("Local spatial frequencies across eccentricities for all stimuli",
                       fontsize=15)
    if save_path is not None:
        g.fig.savefig(save_path, bbox_inches='tight')
    return g


def plot_data(df, x_col='freq_space_distance', median_only=False, ci=68,
              save_path=None, row='varea', **kwargs):
    """plot the raw amplitude estimates, either with or without confidence intervals

    if df is the summary dataframe, we'll use the amplitude_estimate_std_error column as the
    confidence intervals (in this case, ci is ignored). otherwise, we'll estimate them
    directly from the bootstrapped data using np.percentile; in this case, ci determines what
    percentile to plot (by default, the 68% confidence interval)

    x_col determines what to have on the x-axis 'freq_space_distance' or
    'rounded_freq_space_distance' will probably work best. you can try 'freq_space_angle' or 'Local
    spatial frequency (cpd)', but there's no guarantee those will plot well.

    if median_only is True, will not plot confidence intervals.

    kwargs will get passed to plt.scatter and plt.plot, via scatter_ci_dist / scatter_ci_col
    """
    if 'rounded_freq_space_distance' in df.columns:
        col_order = [i for i in LOGPOLAR_SUPERCLASS_ORDER if i in df.stimulus_superclass.unique()]
    else:
        col_order = [i for i in CONSTANT_SUPERCLASS_ORDER if i in df.stimulus_superclass.unique()]

    ylim = kwargs.pop('ylim', None)
    xlim = kwargs.pop('xlim', None)
    aspect = kwargs.pop('aspect', 1)
    g = sns.FacetGrid(df, hue='eccen', palette='Reds', height=5, row=row, col_order=col_order,
                      hue_order=sorted(df.eccen.unique()), col='stimulus_superclass', ylim=ylim,
                      xlim=xlim, aspect=aspect, row_order=sorted(df[row].unique()))
    if 'amplitude_estimate_std_error' in df.columns:
        g.map_dataframe(plot_median, x_col, 'amplitude_estimate_median')
        if not median_only:
            g.map_dataframe(scatter_ci_col, x_col, 'amplitude_estimate_median',
                            'amplitude_estimate_std_error', **kwargs)
    else:
        g.map_dataframe(plot_median, x_col, 'amplitude_estimate')
        if not median_only:
            g.map_dataframe(scatter_ci_dist, x_col, 'amplitude_estimate', ci=ci, **kwargs)
    g.map_dataframe(plot_median, x_col, 'baseline', linestyle='--')
    for ax in g.axes.flatten():
        ax.set_xscale('log', basex=2)
    g.add_legend()
    g.fig.suptitle("Amplitude estimates as a function of frequency")
    plt.subplots_adjust(top=.9)
    if save_path is not None:
        g.fig.savefig(save_path, bbox_inches='tight')
    return g


def _plot_grating_approx_and_save(grating, grating_type, save_path, **kwargs):
    figsize = kwargs.pop('figsize', (5, 5))
    fig, axes = plt.subplots(1, 1, figsize=figsize)
    im_plot(grating, ax=axes, **kwargs)
    if grating_type == 'grating':
        axes.set_title("Windowed view of actual grating")
    elif grating_type == 'approx':
        axes.set_title("Windowed view of linear approximation")
    if save_path is not None:
        try:
            fig.savefig(save_path % grating_type, bbox_inches='tight')
        except TypeError:
            save_path = os.path.splitext(save_path)[0] + "_" + grating_type + os.path.splitext(save_path)[1]
            fig.savefig(save_path, bbox_inches='tight')


def plot_grating_approximation(grating, dx, dy, num_windows=10, phase=0, w_r=None, w_a=None,
                               origin=None, stim_type='logpolar', save_path=None, **kwargs):
    """plot the "windowed approximation" of a grating

    note that this will not create the grating or its gradients (dx/dy), it only plots them. For
    this to work, dx and dy must be in cycles / pixel

    this will work for either regular 2d gratings or the log polar gratings we use as stimuli,
    though it will look slightly different depending on which you do. In the regular case, the
    space between windows will be mid-gray, while for the log polar gratings, it will be
    black. This allows for a creation of a neat illusion for some regular gratings (use
    grating=sfp.utils.create_sin_cpp(1080, .005, .005) to see an example)!

    if `grating` is one of our log polar gratings, then w_r and w_a also need to be set. if it's a
    regular 2d grating, then they should both be None.

    num_windows: int, the number of windows in each direction that we'll use. as this gets larger,
    the approximation will look better and better (and this will take a longer time to run)

    save_path: str, optional. If set, will save plots. in order to make comparison easier, will save
    two separate plots (one of the windowed grating, one of the linear approximation). if save_path
    does not include %s, will append _grating and _approx (respectively) to filename

    kwargs will be past to im_plot.
    """
    size = grating.shape[0]
    # we need to window the gradients dx and dy so they only have values where the grating does
    # (since they're derived analytically, they'll have values everywhere)
    mid_val = {'pilot': 127}.get(stim_type, 128)
    dx = utils.mask_array_like_grating(grating, dx, mid_val)
    dy = utils.mask_array_like_grating(grating, dy, mid_val)
    mask_spacing = int(np.round(size / num_windows))
    # for this to work, the gratings must be non-overlapping
    mask_size = int(np.round(mask_spacing / 2) - 1)
    masked_grating = np.zeros((size, size))
    masked_approx = np.zeros((size, size))
    masks = np.zeros((size, size))
    for i in range(mask_size, size, mask_spacing):
        for j in range(mask_size, size, mask_spacing):
            loc_x, loc_y = i, j
            mask = utils.create_circle_mask(loc_x, loc_y, mask_size, size)
            masks += mask
            masked_grating += mask * grating
            masked_approx += mask * utils.local_grad_sin(dx, dy, loc_x, loc_y, w_r, w_a, phase,
                                                         origin, stim_type)
    # in order to make the space between the masks black, that area should have the minimum
    # value, -1. but for the above to all work, that area needs to be 0, so this corrects that.
    masked_approx[~masks.astype(bool)] -= 1
    masked_grating[~masks.astype(bool)] -= 1
    _plot_grating_approx_and_save(masked_grating, 'grating', save_path, **kwargs)
    _plot_grating_approx_and_save(masked_approx, 'approx', save_path, **kwargs)
    return masked_grating, masked_approx


def add_img_to_xaxis(fig, ax, img, rel_position, size=.1, **kwargs):
    """add image to x-axis

    after calling this, you probably want to make your x axis invisible:
    `ax.xaxis.set_visible(False)` or things will look confusing

    rel_position: float between 0 and 1, specifies where on the x axis you want to place the
    image. You'll need to play arond with this, I don't have a good way of doing this automatically
    (for instance, lining up with existing tick marks). This interacts with size. if you want the
    left edge to line up with the beginning of the x-axis, this should be 0, but if you want the
    right edge to line up with the end of the x-axis, this should be around 1-size

    size: float between 0 and 1, size of image, relative to overall plot size. it appears that
    around .1 or .2 is a good size.
    """
    xl, yl, xh, yh = np.array(ax.get_position()).ravel()
    w = xh - xl

    ax1 = fig.add_axes([xl + w*rel_position, yl-size, size, size])
    ax1.axison = False
    im_plot(img, ax=ax1, **kwargs)


def stimuli_linear_approximation(stim, stim_df, stim_type, num_windows=11, stim_idx=None, phi=None,
                                 freq_space_distance=None, freq_space_angle=None,
                                 stimulus_superclass=None, save_path=None, **kwargs):
    """plot the linear approximation of specific stimulus
    """
    if stim_idx is None:
        stim_idx = utils.find_stim_idx(stim_df, stimulus_superclass=stimulus_superclass, phi=phi,
                                       freq_space_distance=freq_space_distance,
                                       freq_space_angle=freq_space_angle)
    props = stim_df.loc[stim_idx]
    freqs = {}
    for f in ['w_r', 'w_a', 'w_x', 'w_y']:
        try:
            freqs[f] = props[f]
        except KeyError:
            freqs[f] = None
    stim = stim[stim_idx]
    dx, dy, _, _ = sfp_stimuli.create_sf_maps_cpp(props.res, stim_type=stim_type, **freqs)
    return plot_grating_approximation(stim, dx, dy, num_windows, props.phi, w_r=freqs['w_r'],
                                      w_a=freqs['w_a'], stim_type=stim_type,
                                      save_path=save_path, **kwargs)


def stimuli(stim, stim_df, save_path=None, **kwargs):
    """plot a bunch of stimuli with specific properties, pulled out of stim_df

    possible keys for kwargs: {'w_r'/'w_x', 'w_a'/'w_y', 'phi', 'res', 'alpha', 'stimulus_index',
    'class_idx', 'stimulus_superclass', 'freq_space_angle', 'freq_space_distance'}. The values
    should be either a list or a single value. if a single value, will assume that all stimuli
    share that property. all lists should be the same length. if a property isn't set, then we
    assume it's not important and so will grab the lowest stimuli with the lowest index that
    matches all specified properties.
    """
    stim_props = {}
    stim_num = None
    figsize = kwargs.pop('figsize', None)
    for k, v in kwargs.items():
        if hasattr(v, "__iter__") and not isinstance(v, str):
            if stim_num is None:
                stim_num = len(v)
            else:
                if stim_num != len(v) and len(v) != 1:
                    raise Exception("All stimulus properties must have the same length!")
            stim_props[k] = v
        else:
            stim_props[k] = [v]
    if stim_num is None:
        stim_num = 1
    for k, v in stim_props.items():
        if len(v) == 1:
            stim_props[k] = stim_num * v
    stim_idx = []
    for i in range(stim_num):
        stim_idx.append(utils.find_stim_idx(stim_df,
                                            **dict((k, v[i]) for k, v in stim_props.items())))
    if figsize is None:
        figsize = (5 * min(stim_num, 4), 5 * np.ceil(stim_num / 4.))
    fig = plt.figure(figsize=figsize)
    # ADD DESCRIPTIVE TITLES
    for i, idx in enumerate(stim_idx):
        ax = fig.add_subplot(np.ceil(stim_num / 4.).astype(int), min(stim_num, 4), i+1)
        im_plot(stim[idx, :, :], ax=ax)
    plt.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)


def plot_tuning_curve(ci_vals=[16, 84], norm=False, xlim=None, style=None,
                      dashes_dict={}, **kwargs):
    data = kwargs.pop('data')
    color = kwargs.pop('color')
    ax = kwargs.pop('ax', plt.gca())
    if xlim is not None:
        if xlim == 'data':
            xlim = (data.frequency_value.min(), data.frequency_value.max())
        xlim = np.logspace(np.log10(xlim[0]), np.log10(xlim[1]))
    if style is not None:
        data = data.groupby(style)
    else:
        data = [(None, data)]
    for m, d in data:
        dashes = dashes_dict.get(m, '')
        if 'bootstrap_num' in d.columns and d.bootstrap_num.nunique() > 1:
            xs, ys = [], []
            for n, g in d.groupby('bootstrap_num'):
                x, y = tuning_curves.get_tuning_curve_xy_from_df(g, norm=norm, x=xlim)
                xs.append(x)
                ys.append(y)
            xs = np.array(xs)
            if (xs != xs[0]).any():
                raise Exception("Somehow we got different xs for the tuning curves of some "
                                "bootstraps!")
            ys = np.array(ys)
            y_median = np.median(ys, 0)
            y_cis = np.percentile(ys, ci_vals, 0)
            ax.fill_between(xs[0], y_cis[0], y_cis[1], alpha=.2, facecolor=color)
            ax.semilogx(xs[0], y_median, basex=2, color=color, dashes=dashes, **kwargs)
        else:
            x, y = tuning_curves.get_tuning_curve_xy_from_df(d, norm=norm, x=xlim)
            ax.semilogx(x, y, basex=2, color=color, dashes=dashes, **kwargs)


def _restrict_df(df, **kwargs):
    for k, v in kwargs.items():
        try:
            df = df[df[k].isin(v)]
        except TypeError:
            df = df[df[k] == v]
    return df


def check_tuning_curves(tuning_df, save_path_template, **kwargs):
    """create all the tuning curve plots

    this takes the dataframe containing the tuning curves and creates plots of all of them, so they
    can be visibly checked. note that this will take a while and create *many* plots, especially
    when run on the full dataframes. It is thus *not* meant to be run from a notebook and it will
    close the plots as it creates and saves them.

    kwargs can contain columns in the tuning_df and values to limit them to.
    """
    tuning_df = _restrict_df(tuning_df, **kwargs)
    gb_cols = ['varea']
    title_template = 'varea={}'
    if 'bootstrap_num' in tuning_df.columns:
        gb_cols += ['bootstrap_num']
        title_template += ', bootstrap={:02d}'
    mode_bounds = (tuning_df.mode_bound_lower.unique()[0], tuning_df.mode_bound_upper.unique()[0])
    for n, g in tuning_df.groupby(gb_cols):
        f = sns.FacetGrid(g, row='eccen', col='stimulus_superclass', hue='frequency_type',
                          xlim=mode_bounds, aspect=.7, height=5)
        f.map(plt.scatter, 'frequency_value', 'amplitude_estimate')
        f.map_dataframe(plot_tuning_curve)
        f.map_dataframe(plot_median, 'frequency_value', 'baseline', linestyle='--')
        f.add_legend()
        f.set_titles("eccen={row_name} | {col_name}")
        if len(gb_cols) == 1:
            # then there's only one value in n (and thus, in gb_cols)
            suptitle = title_template.format(n)
        else:
            suptitle = title_template.format(*n)
        f.fig.suptitle(suptitle)
        plt.subplots_adjust(top=.95)
        f.savefig(save_path_template % (suptitle.replace(', ', '_')))
        plt.close(f.fig)


def check_hypotheses(tuning_df, save_path_template=None, norm=False, ci_vals=[16, 84],
                     plot_data=True, **kwargs):
    tuning_df = _restrict_df(tuning_df, **kwargs)
    gb_cols = ['varea']
    title_template = 'varea={}'
    col_order = [i for i in LOGPOLAR_SUPERCLASS_ORDER+CONSTANT_SUPERCLASS_ORDER
                 if i in tuning_df.stimulus_superclass.unique()]
    for n, g in tuning_df.groupby(gb_cols):
        f = sns.FacetGrid(g, hue='eccen', palette='Reds', height=5, row='frequency_type',
                          col='stimulus_superclass', col_order=col_order)
        if plot_data:
            f.map_dataframe(plot_median, 'frequency_value', 'amplitude_estimate',
                            plot_func=plt.scatter)
        f.map_dataframe(plot_tuning_curve, norm=norm, ci_vals=ci_vals)
        for ax in f.axes.flatten():
            ax.set_xscale('log', basex=2)
            ax.set_xlim((2**-5, 2**10))
            if norm:
                ax.set_ylim((0, 1.2))
        f.add_legend()
        suptitle = title_template.format(n)
        f.fig.suptitle("Median amplitude estimates with tuning curves, %s" % suptitle)
        plt.subplots_adjust(top=.93)
        f.set_titles("{row_name} | {col_name}")
        if save_path_template is not None:
            f.fig.savefig(save_path_template % suptitle, bbox_inches='tight')


def check_hypotheses_with_data(tuning_df, save_path_template=None, ci_vals=[16, 84], **kwargs):
    check_hypotheses(tuning_df, save_path_template, False, ci_vals, True, **kwargs)


def check_hypotheses_normalized(tuning_df, save_path_template=None, ci_vals=[16, 84], **kwargs):
    check_hypotheses(tuning_df, save_path_template, True, ci_vals, False, **kwargs)


def tuning_params(tuning_df, save_path=None, **kwargs):
    tuning_df = _restrict_df(tuning_df, **kwargs)
    tuning_df = tuning_df[['frequency_type', 'tuning_curve_amplitude', 'tuning_curve_sigma',
                           'tuning_curve_peak', 'tuning_curve_bandwidth']]
    tuning_df['tuning_curve_peak'] = np.log2(tuning_df.tuning_curve_peak)
    g = sns.PairGrid(tuning_df, hue='frequency_type', aspect=1)
    g.map_offdiag(plt.scatter)
    g.map_diag(sns.distplot)
    g.add_legend()
    if save_path is not None:
        g.fig.savefig(save_path)


def period_summary_plot(df, pRF_size_slope=.25394, pRF_size_offset=.100698,
                        model=linear_model.LinearRegression(), n_windows=4, size=1080,
                        max_visual_angle=24, plot_view='full', center_spot_rad=2,
                        stimulus_superclass=None, save_path=None):
    """make plot that shows the optimal number of periods per receptive field

    df: dataframe containing the summarized preferred periods. should contain three columns:
    stimulus_superclass, eccen, and preferred_period. will fit model separately to each
    stimulus_superclass (by default, linear regression, fitting the intercept) and then, at each
    eccentricity, show the appropriate period (from the fitted line). because we allow the
    intercept to be non-zero

    this works by using the coefficients of the linear fits (with zero intercept) relating
    eccentricity to the period of the optimal grating stimulus (from measurements for both radial
    and angular stimuli) and to V1 receptive field size. We show the views of the radial stimuli
    along the vertical axis and the views of the angular along the horizontal axis.

    pRF_size_slope should be for the diameter of what you want to display. for example, the default
    is 4 * stddev, or the diameter of two standard deviations.

    n_windows: int, the number of windows on each side of the origin to show

    plot_view: {'full', 'quarter', 'aligned'}. whether to plot a full, quarter, or aligned view. if
    aligned, can only plot one stimulus superclass and will do always do so along the horizontal
    meridian (for combining by hand afterwards).

    stimulus_superclass: which stimulus superclasses to plot. if None, will plot all that are in
    the dataframe. note that we don't re-adjust spacing to make it look good for fewer than 4
    superclasses, so that's on you.
    """
    def get_logpolar_freq(slope, intercept, ecc):
        coeff = (slope*ecc + intercept) / ecc
        return np.round((2 * np.pi) / coeff)

    def fit_model(data, model=linear_model.LinearRegression()):
        x = data.eccen.values
        y = data.preferred_period.values
        model.fit(x.reshape(-1, 1), y)
        return pd.Series({'coeff': model.coef_[0], 'intercept': model.intercept_})

    def logpolar_solve_for_global_phase(x, y, w_r, w_a, local_phase=0):
        origin = ((size+1) / 2., (size+1) / 2.)
        x_orig, y_orig = np.meshgrid(np.array(range(1, size+1))-origin[0],
                                     np.array(range(1, size+1))-origin[1])
        local_x = x_orig[y, x]
        local_y = y_orig[y, x]
        return np.mod(local_phase - (((w_r*np.log(2))/2.)*np.log2(local_x**2+local_y**2) +
                                     w_a*np.arctan2(local_y, local_x)), 2*np.pi)

    if stimulus_superclass is None:
        stimulus_superclass = df.stimulus_superclass.unique()
    if plot_view == 'aligned' and len(stimulus_superclass) != 1:
        raise Exception("Can only plot aligned view if plotting 1 stimulus_superclass")
    df = df.groupby('stimulus_superclass').apply(fit_model)
    windowed_plot = np.zeros((size, size))
    R = sfp_stimuli.mkR(size) * (float(max_visual_angle) / size)
    ecc_to_pix = pRF_size_slope * (float(size) / max_visual_angle) + pRF_size_offset
    masks = np.zeros((size, size))
    meridian = int(size / 2)
    # we put this into masks so it doesn't get adjusted at the end and we set it to -1 so it
    # appears black.
    masks[meridian-center_spot_rad:meridian+center_spot_rad,
          meridian-center_spot_rad:meridian+center_spot_rad] = 1
    windowed_plot[masks.astype(bool)] = -1
    view_range = range(meridian, size, int(meridian / (n_windows+1)))[1:]
    for loc in view_range:
        # we do x and y separately because there's a chance a rounding issue will mean they differ
        # slightly
        if plot_view == 'full':
            diag_value_1 = (loc - meridian) * np.sin(np.pi / 4)
            diag_value_2 = (loc - meridian) * -np.sin(np.pi / 4)
            window_locs = [(loc, meridian, 'radial'), (meridian, loc, 'angular'),
                           (size-loc, meridian, 'radial'), (meridian, size-loc, 'angular'),
                           (meridian+diag_value_1, meridian+diag_value_1, 'forward spiral'),
                           (meridian+diag_value_1, meridian+diag_value_2, 'reverse spiral'),
                           (meridian+diag_value_2, meridian+diag_value_2, 'forward spiral'),
                           (meridian+diag_value_2, meridian+diag_value_1, 'reverse spiral')]
        elif plot_view == 'quarter':
            diag_value_1 = (loc - meridian) * np.sin(np.pi / 6)
            diag_value_2 = (loc - meridian) * np.sin(np.pi / 3)
            window_locs = [(size-loc, meridian, 'radial'), (meridian, loc, 'angular'),
                           (meridian-diag_value_1, meridian+diag_value_2, 'forward spiral'),
                           (meridian-diag_value_2, meridian+diag_value_1, 'reverse spiral')]
        elif plot_view == 'aligned':
            window_locs = [(meridian, loc, stimulus_superclass[0])]
        for loc_y, loc_x, stim_class in window_locs:
            if stim_class not in stimulus_superclass:
                continue
            loc_x, loc_y = int(loc_x), int(loc_y)
            ecc = R[loc_y, loc_x]
            # ecc * ecc_to_pix gives you the diameter, but we want the radius
            mask = utils.create_circle_mask(loc_x, loc_y, (ecc * ecc_to_pix) / 2, size)
            masks += mask
            opt_w = get_logpolar_freq(df.loc[stim_class].coeff, df.loc[stim_class].intercept, ecc)
            if stim_class == 'angular':
                phase = logpolar_solve_for_global_phase(loc_x, loc_y, 0, opt_w)
                windowed_plot += mask * sfp_stimuli.log_polar_grating(size, w_a=opt_w, phi=phase)
            elif stim_class == 'radial':
                phase = logpolar_solve_for_global_phase(loc_x, loc_y, opt_w, 0)
                windowed_plot += mask * sfp_stimuli.log_polar_grating(size, w_r=opt_w, phi=phase)
            elif stim_class == 'forward spiral':
                opt_w = np.round(opt_w / np.sqrt(2))
                phase = logpolar_solve_for_global_phase(loc_x, loc_y, opt_w, opt_w)
                windowed_plot += mask * sfp_stimuli.log_polar_grating(size, w_r=opt_w, w_a=opt_w,
                                                                      phi=phase)
            elif stim_class == 'reverse spiral':
                opt_w = np.round(opt_w / np.sqrt(2))
                phase = logpolar_solve_for_global_phase(loc_x, loc_y, opt_w, -opt_w)
                windowed_plot += mask * sfp_stimuli.log_polar_grating(size, w_r=opt_w, w_a=-opt_w,
                                                                      phi=phase)
    windowed_plot[~masks.astype(bool)] += 1
    fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    im_plot(windowed_plot, ax=ax)
    if save_path is not None:
        fig.savefig(save_path)
    return windowed_plot


def model_schematic(model, axes=None, ylims=None, title=True,
                    orientation=np.linspace(0, np.pi, 4, endpoint=False)):
    """Examine model predictions, intended for example models (not ones fit to data)

    In order to better understand the model, it's helpful to examine the
    predictions for several toy models to see the effect of changing
    parameters and get an intuition for what's going on. This plot is an
    attempt to help with that by creating two plots next to each other,
    showing the preferred period as a function of eccentricity and
    retinotopic angle (in separate plots, each showing one slice of the
    other; both in relative reference frame).

    This function is intended to be called by figures.model_schematic().

    It's recommended that each axis have size (5, 5).

    NOTE: we remove the legend from each plot, because otherwise there's
    one per plot and they take up too much space. It's recommended that
    you create your own by grabbing the handles and labels from the
    returned axes and placing on its own set of axes:

    ```
    fig = plt.figure(figsize=(15, 5))
    axes = []
    for i in range(4):
        ax = fig.add_subplot(1, 3, i+1,
                             projection=['rectilinear', 'polar', 'rectilinear'][i])
        axes.append(ax)
    axes = model_schematic(model, axes)
    # relative reference frame legend
    axes[-1].legend(*axes[0].get_legend_handles_labels(), loc='upper left')
    ```

    Parameters
    ----------
    model : sfp.model.LogGaussianDonut
        Instantiated model that you want to generate the predictions for
    axes : list or None, optional
        A list of axes to create the plots on. There must be at least
        two of them, the first must have a rectilinear projection (the
        default), and the second must have polar projections (any
        further axes will be ignored). If None, we create two axes in a
        row with figsize=(10, 5).
    ylims : list or None, optional
        A list of three tuples, the ylim value to use for each plot
        (ylim corresponds to rlim for polar plots). If None, we use the
        default. Used for making the same limits across multiple
        calls to this function.
    title : bool, optional
        whether to add a title or not

    Returns
    -------
    axes : list
        The axes with the plots

    """
    if axes is None:
        fig = plt.figure(figsize=(10, 5))
        axes = []
        for i in range(2):
            ax = fig.add_subplot(1, 2, i+1, projection=['rectilinear', 'polar'][i])
            axes.append(ax)
    single_ret_angle = 0
    single_ecc = 6
    ecc = np.arange(12)
    pref_period = analyze_model.create_preferred_period_df(model, reference_frame='relative',
                                                           retinotopic_angle=[single_ret_angle],
                                                           eccentricity=ecc,
                                                           orientation=orientation)
    ret_angle = np.linspace(0, 2*np.pi, 49)
    rel_contour = analyze_model.create_preferred_period_df(model, reference_frame='relative',
                                                           eccentricity=[single_ecc],
                                                           retinotopic_angle=ret_angle,
                                                           orientation=orientation)
    titles = [f'Preferred period at retinotopic angle {single_ret_angle}',
              f'Preferred period at eccentricity {single_ecc}']
    dfs = [pref_period, rel_contour]
    projs = ['rectilinear', 'polar']
    if len(axes) == 1:
        if axes[0].name == 'rectilinear':
            dfs = [dfs[0]]
            projs = [projs[0]]
            titles = [titles[0]]
        elif axes[0].name == 'polar':
            dfs = [dfs[1]]
            projs = [projs[1]]
            titles = [titles[1]]
    for i, (df, ax, proj, t) in enumerate(zip(dfs, axes, projs, titles)):
        if ax.name != proj:
            raise Exception(f"Axes must have projection {proj}, not {ax.name}!")
        if proj == 'rectilinear':
            x = 'Eccentricity (deg)'
            single_x = single_ecc
        else:
            x = 'Retinotopic angle (rad)'
            single_x = single_ret_angle
        order = [k for k in stimulus_type_order(df.reference_frame.unique()[0])
                 if k in df['Stimulus type'].unique()]
        pal = get_palette('stimulus_type', df.reference_frame.unique()[0],
                          df['Stimulus type'].unique(), True)
        sns.lineplot(x, 'Preferred period (deg)', 'Stimulus type', data=df, ax=ax, hue_order=order,
                     palette=pal, estimator=np.median, ci=68)
        ax.legend_.remove()
        if i > 0:
            ax.set_ylabel('')
        if title:
            ax.set_title(t, y=[1.1, 1.1][i])
        if ylims is not None:
            ax.set_ylim(ylims[i])
        restricted = df[df['Eccentricity (deg)'] == single_ecc]['Preferred period (deg)']
        if proj == 'rectilinear':
            ax.axhline(color='gray', linestyle='--')
            ax.axvline(color='gray', linestyle='--')
        else:
            ax.set(yticklabels=[0, '', 1, '', 2, '', 3], yticks=[0, .5, 1, 1.5, 2, 2.5, 3])
        if len(axes) > 1:
            # only want this if we're plotting both the linear and polar plots
            ax.vlines(single_x, restricted.min()-.5, restricted.max()+.5, 'r', '--')
    return axes


def feature_df_plot(feature_df, hue="Stimulus type", col='Retinotopic angle (rad)', row=None,
                    plot_func=sns.lineplot, x='Eccentricity (deg)', y='Preferred period (deg)',
                    yticks=[0, 1, 2], xticks=[0, 2, 4, 6, 8, 10], height=4, aspect=1,
                    title='Preferred period', top=.85, pal=None, col_order=None, row_order=None,
                    ylim=None, xlim=None, ci=68, col_wrap=None, pre_boot_gb_func=None,
                    pre_boot_gb_cols=['subject', 'reference_frame', 'Stimulus type',
                                      'bootstrap_num', 'Eccentricity (deg)'],
                    facetgrid_legend=True, hue_kws={}, **kwargs):
    """Create plot from feature_df

    This function takes the feature_df created by
    sfp.analyze_model.create_feature_df and makes summary plots. The
    default should do more or less what you want it to, but there's a
    lot of customizability.

    Note that this makes a non-polar plot (it plots y as a function of
    x), and so the intended use is for the preferred_period
    feature_df. For the preferred period and max amplitude contours, use
    feature_df_polar_plot

    The majority of the arguments are passed right to sns.FacetGrid

    There are two major choices for `plot_func`: `sns.lineplot` and
    `sfp.plotting.scatter_ci_dist`. The major difference is how they
    draw CIs:

    1. `sns.lineplot` draws CIs by drawing its own bootstraps from the
       data present in the df. So if your df contains 12 independent
       subjects and you want to draw your CIs summarizing how these
       predictions differ across subjects, use this.

    2. `sfp.plotting.scatter_ci_dist` draws CIs based on a distribution
       already in the df. That is, we assume you've already generated
       your bootstrapped distribution and want the plotting function to
       create the CIs based on the percentiles of the data already in
       the df. For example, we get 100 bootstrapped estimates of each
       voxels' response to the stimuli, and fit a model to each of these
       bootstraps separately. These bootstraps are *not* independent
       (they're generated by sampling from runs, which are), and so
       using `sns.lineplot` above to resample from them is
       inappropriate. Instead, `scatter_ci_dist` will create the CIs
       from the df directly.

    If you're using `scatter_ci_dist` for the intended purpose above,
    you probably want to add the following kwargs (which will get passed
    directly to `scatter_ci_dist`): `draw_ctr_pts=False, ci_mode='fill',
    join=True`.

    Parameters
    ----------
    feature_df : pd.DataFrame
        The feature dataframe, containing the preferred period as a
        function of eccentricity, at multiple stimulus orientation and
        retinotopic angles
    hue : str, optional
        a column in feature_df, which feature to use for the hue of plot
    col : str, optional
        a column in feature_df, which feature to facet on the columns
    row : str, optional
        a column in feature_df, which feature to facet on the rows
    plot_func : callable, optional
        The plot function to map on the FacetGrid. First two args should
        be x and y, should accept ci kwarg. Will call using
        map_dataframe. Note that different choices here will affects how
        we raw CIs, see above for more details
    x : str, optional
        a column in feature_df, which feature to plot on the x-axis
    y : str, optional
        a column in feature_df, which feature to plot on the y-axis
    {y, x}ticks : list, optional
        list of floats, which y- and x-ticks to include on the plot
    height : float, optional
        The height of each individual subplot
    aspect : float, optional
        The aspect ratio of each individual subplot
    title : str or None, optional
        The super-title of the plot. If None, we don't add a
        super-title, and we will not adjust the subplot spacing
    top : float, optional
        The amount to adjust the subplot spacing at the top so the title
        is above the subplots (with a call to
        g.fig.subplots_adjust(top=top)). If title is None, this is
        ignored.
    pal : palette name, list, dict, or None, optional
        palette to pass to sns.FacetGrid for specifying the colors to
        use. if None and hue=="Stimulus type", we use the defaults given
        by sfp.plotting.stimulus_type_palette.
    {col, row}_order : list or None, optional
        the order for the columns and rows. If None, we use the default
    {y, x}lim : tuples or None, optional
        if not None, the limits for the y- and x-axes for all subplots.
    ci : int, optional
        the size of the confidence intervals to plot. see the docstring
        of plot_func for more details
    col_wrap : int or None, optional
        'wrap' the column variable at this width, so that the column
        facets span multiple rows. will throw an exception if col_wrap
        and row are both not None
    pre_boot_gb_func : str,, callable or None, optional
        feature_df contains a lot of info, and you may want to collapse
        over some of those dimensions. In order to make sure those
        dimensions are collapsed over appropriately, this function can
        perform an (optional) groupby before creating the FacetGrid. If
        this is not None, we will create the plot with
        feature_df.groupby(pre_boot_gb_cols).agg(pre_boot_gb_func).reset_index(). The
        intended use case is for, e.g., averaging over all retinotopic
        angles by setting this to 'mean'. See the docstring of
        pandas.groupby.agg for more info on possible arguments
    pre_boot_gb_cols : list, optional
        The columns to use for the optional groupby. See above for more
        details
    facetgrid_legend : bool, optional
        whether to use the `FacetGrid.add_legend` method to add a
        legend. if False, will not add a legend (and so you must do it
        yourself)
    hue_kws : dict, optional
        Other keyword arguments to insert into the plotting call to let other
        plot attributes vary across levels of the hue variable (e.g. the
        markers in a scatterplot).
    kwargs :
        passed to plot_func

    Returns
    -------
    g : sns.FacetGrid
        The FacetGrid containing the plot

    """
    if pal is None and hue == 'Stimulus type':
        pal = stimulus_type_palette(feature_df.reference_frame.unique())
    if col_order is None and col == 'Stimulus type':
        col_order = stimulus_type_order(feature_df.reference_frame.unique())
    if row_order is None and row == 'Stimulus type':
        row_order = stimulus_type_order(feature_df.reference_frame.unique())
    if pre_boot_gb_func is not None:
        feature_df = feature_df.groupby(pre_boot_gb_cols).agg(pre_boot_gb_func).reset_index()
    # facetgrid seems to ignore the defaults for these, but we want to use them
    # so its consistent with other figures
    gridspec_kws = {k: mpl.rcParams[f'figure.subplot.{k}']
                    for k in ['top', 'bottom', 'left', 'right']}
    g = sns.FacetGrid(feature_df, hue=hue, col=col, row=row, height=height, aspect=aspect,
                      palette=pal, xlim=xlim, ylim=ylim, col_wrap=col_wrap, col_order=col_order,
                      row_order=row_order, gridspec_kws=gridspec_kws, hue_kws=hue_kws)
    g.map_dataframe(plot_func, x, y, ci=ci, estimator=np.median, **kwargs)
    if col_wrap is not None:
        g_axes = g.axes
        # if col_wrap is not None, g.axes will be a single list of axes. we
        # want it to be a list of lists, where the i-th entry contains a list
        # with all axes in the i-th column
        g_axes = [g_axes[col_wrap*i:col_wrap*(i+1)] for i in range(len(g_axes)//col_wrap+1)]
        # drop any empty lists
        g_axes = [ax for ax in g_axes if len(ax) > 0]
        g._axes = np.array(g_axes)
    if facetgrid_legend:
        g.add_legend()
    for ax in g.axes.flatten():
        if ax.get_ylim()[0] < 0:
            ax.axhline(color='gray', linestyle='--')
        if ax.get_xlim()[0] < 0:
            ax.axvline(color='gray', linestyle='--')
        if yticks is not None:
            ax.set_yticks(yticks)
        if xticks is not None:
            ax.set_xticks(xticks)
    if title is not None:
        g.fig.suptitle(title)
        g.fig.subplots_adjust(top=top)
    if col == 'subject' and feature_df[col].nunique() == 1:
        g.set(title='')
    return g


def feature_df_polar_plot(feature_df, hue="Stimulus type", col='Preferred period (deg)', row=None,
                          plot_func=sns.lineplot, theta='Retinotopic angle (rad)',
                          r='Eccentricity (deg)', r_ticks=None, theta_ticks=None, r_ticklabels=None,
                          theta_ticklabels=None, all_tick_labels=[], height=4, aspect=1, title='Preferred period contours',
                          top=.76, hspace=.3, wspace=.1, pal=None, col_order=None, row_order=None,
                          title_position=[.5, 1.15], ylabelpad=30, legend_position=None, ylim=None,
                          xlim=None, ci=68, col_wrap=None, pre_boot_gb_func=None,
                          pre_boot_gb_cols=['subject', 'reference_frame', 'Stimulus type',
                                            'Eccentricity (deg)'],
                          facetgrid_legend=True, **kwargs):
    """Create polar plot from feature_df

    This function takes the feature_df created by
    sfp.analyze_model.create_feature_df and makes summary plots. The
    default should do more or less what you want it to, but there's a
    lot of customizability.

    Note that this makes a polar plot (it plots r as a function of
    theta), and so the intended use is for the preferred period and max
    amplitude contours feature_df. For the preferred period, use
    feature_df_plot

    The majority of the arguments are passed right to sns.FacetGrid

    There are two major choices for `plot_func`: `sns.lineplot` and
    `sfp.plotting.scatter_ci_dist`. The major difference is how they
    draw CIs:

    1. `sns.lineplot` draws CIs by drawing its own bootstraps from the
       data present in the df. So if your df contains 12 independent
       subjects and you want to draw your CIs summarizing how these
       predictions differ across subjects, use this.

    2. `sfp.plotting.scatter_ci_dist` draws CIs based on a distribution
       already in the df. That is, we assume you've already generated
       your bootstrapped distribution and want the plotting function to
       create the CIs based on the percentiles of the data already in
       the df. For example, we get 100 bootstrapped estimates of each
       voxels' response to the stimuli, and fit a model to each of these
       bootstraps separately. These bootstraps are *not* independent
       (they're generated by sampling from runs, which are), and so
       using `sns.lineplot` above to resample from them is
       inappropriate. Instead, `scatter_ci_dist` will create the CIs
       from the df directly.

    Parameters
    ----------
    feature_df : pd.DataFrame
        The feature dataframe, containing the preferred period as a
        function of eccentricity, at multiple stimulus orientation and
        retinotopic angles
    hue : str, optional
        a column in feature_df, which feature to use for the hue of plot
    col : str, optional
        a column in feature_df, which feature to facet on the columns
    row : str, optional
        a column in feature_df, which feature to facet on the rows
    plot_func : callable, optional
        The plot function to map on the FacetGrid. First two args should
        be x and y, should accept ci kwarg. Will call using
        map_dataframe. Note that different choices here will affect how
        we create CIs, see above for more details
    theta : str, optional
        a column in feature_df, which feature to plot as polar angle
    r : str, optional
        a column in feature_df, which feature to plot as distance from
        the origin
    {r, theta}_ticks : list, optional
        list of floats, which r- and theta-ticks to include on the plot
    {r, theta}_ticklabels : list, optional
        list of floats/strs, which r- and theta-tick labels to include
        on the plot
    all_tick_labels : list, optional
        by default, sns.FacetGrid only puts tick labels on the bottom-
        and left-most facets. this works well for cartesian plots, but
        less well for polar ones. If you want to make sure that the tick
        labels are shown on each facet, include the axis here. possible
        values are: 'r', 'theta'. If list is empty, then we don't change
        anything
    height : float, optional
        The height of each individual subplot
    aspect : float, optional
        The aspect ratio of each individual subplot
    title : str or None, optional
        The super-title of the plot. If None, we don't add a
        super-title, and we will not adjust the subplot spacing
    top : float, optional
        The amount to adjust the subplot spacing at the top so the title
        is above the subplots (with a call to
        g.fig.subplots_adjust(top=top)). If title is None, this is
        ignored.
    hspace : float, optional
        the amount of height reserved for space between subplots,
        expressed as a fraction of the average axis width
    wspace : float, optional
        the amount of width reserved for space between subplots,
        expressed as a fraction of the average axis width
    pal : palette name, list, dict, or None, optional
        palette to pass to sns.FacetGrid for specifying the colors to
        use. if None and hue=="Stimulus type", we use the defaults given
        by sfp.plotting.stimulus_type_palette.
    {col, row}_order : list or None, optional
        the order for the columns and rows. If None, we use the default
    title_position : 2-tuple, optional
        The position (in x, y) of each subplots' title (not the
        super-title)
    ylabelpad : int
        number of pixels to "pad" the y-label by, so that it doesn't
        overlap with the polar plot
    legend_position : 2-tuple or None, optional
        if not None, the x, y position of the legend. if None, use
        default position
    {y, x}lim : tuples or None, optional
        if not None, the limits for the y- and x-axes for all subplots.
    ci : int, optional
        the size of the confidence intervals to plot. see the docstring
        of plot_func for more details
    col_wrap : int or None, optional
        'wrap' the column variable at this width, so that the column
        facets span multiple rows. will throw an exception if col_wrap
        and row are both not None
    pre_boot_gb_func : callable or None, optional
        feature_df contains a lot of info, and you may want to collapse
        over some of those dimensions. In order to make sure those
        dimensions are collapsed over appropriately, this function can
        perform an (optional) groupby before creating the FacetGrid. If
        this is not None, we will create the plot with
        feature_df.groupby(pre_boot_gb_cols).agg(pre_boot_gb_func).reset_index(). The
        intended use case is for, e.g., averaging over all retinotopic
        angles by setting this to 'mean'. See the docstring of
        pandas.groupby.agg for more info on possible arguments
    pre_boot_gb_cols : list, optional
        The columns to use for the optional groupby. See above for more
        details
    facetgrid_legend : bool, optional
        whether to use the `FacetGrid.add_legend` method to add a
        legend. if False, will not add a legend (and so you must do it
        yourself)
    kwargs :
        passed to plot_func

    Returns
    -------
    g : sns.FacetGrid
        The FacetGrid containing the plot

    """
    if pal is None and hue == 'Stimulus type':
        pal = stimulus_type_palette(feature_df.reference_frame.unique())
    if col_order is None and col == 'Stimulus type':
        col_order = stimulus_type_order(feature_df.reference_frame.unique())
    if row_order is None and row == 'Stimulus type':
        row_order = stimulus_type_order(feature_df.reference_frame.unique())
    if pre_boot_gb_func is not None:
        feature_df = feature_df.groupby(pre_boot_gb_cols).agg(pre_boot_gb_func).reset_index()
    # facetgrid seems to ignore the defaults for these, but we want to use them
    # so its consistent with other figures
    gridspec_kws = {k: mpl.rcParams[f'figure.subplot.{k}']
                    for k in ['top', 'bottom', 'left', 'right']}
    g = sns.FacetGrid(feature_df, col=col, hue=hue, row=row, subplot_kws={'projection': 'polar'},
                      despine=False, height=height, aspect=aspect, palette=pal, xlim=xlim,
                      ylim=ylim, col_wrap=col_wrap, col_order=col_order, row_order=row_order,
                      gridspec_kws=gridspec_kws)
    g.map_dataframe(plot_func, theta, r, ci=ci, estimator=np.median, **kwargs)
    if col_wrap is not None:
        g_axes = g.axes
        # if col_wrap is not None, g.axes will be a single list of axes. we
        # want it to be a list of lists, where the i-th entry contains a list
        # with all axes in the i-th column
        g_axes = [g_axes[col_wrap*i:col_wrap*(i+1)] for i in range(len(g_axes)//col_wrap+1)]
        # drop any empty lists
        g_axes = [ax for ax in g_axes if len(ax) > 0]
        g._axes = np.array(g_axes)
    for i, axes in enumerate(g.axes):
        for j, ax in enumerate(axes):
            ax.title.set_position(title_position)
            # we do this for all axes in the first column
            if j == 0:
                ax.yaxis.labelpad = ylabelpad
            if r_ticks is not None:
                ax.set_yticks(r_ticks)
            if r_ticklabels is not None:
                ax.set_yticklabels(r_ticklabels)
            if 'r' in all_tick_labels:
                ax.tick_params(labelleft=True)
            if theta_ticks is not None:
                ax.set_xticks(theta_ticks)
            if theta_ticklabels is not None:
                ax.set_xticklabels(theta_ticklabels)
            if 'theta' in all_tick_labels:
                ax.tick_params(labelbottom=True)
    if facetgrid_legend:
        if legend_position is not None:
            g.add_legend(bbox_to_anchor=legend_position)
        else:
            g.add_legend()
    if title is not None:
        g.fig.suptitle(title)
        g.fig.subplots_adjust(top=top)
    g.fig.subplots_adjust(hspace=hspace, wspace=wspace)
    return g


def flat_cortex_plot(freesurfer_sub, plot_property, output_path=None, mask=None):
    """Create a plot of a property on a flattened view of the cortical surface

    I'm not aware of an easy scriptable way to create 3d plots of the
    cortex from a consistent viewpoint, but, since we only care about
    primary visual cortex, a flattened view of the cortical surface
    works pretty well. This function uses Noah Benson's neuropythy
    library to plot a property on top of the cortical surface of both
    hemispheres, flattened to a circle, from both posterior and anterior
    views.

    Parameters
    ----------
    freesurfer_sub : str
        The freesurfer subject to use. This can be either the name
        (e.g., wlsubj045; in which case the environmental variable
        SUBJECTS_DIR must be set) or a path to the freesurfer folder. It
        will be passed directly to neuropythy.freesurfer_subject, so see
        the docstring of that function for more details
    plot_property : str or dict
        The property to plot as an overlay on the flattened cortical
        surface. This can either be a str, in which case it's a property
        of the subject, coming from surfaces already found in the
        freesurfer folder, or a dictionary of arrays (with keys lh, rh)
        containing the labels of the property.
    output_path : str or None, optional
        if not None, the path to save the resulting figure at. If None,
        will not save
    mask : tuple or None, optional
        a mask to restrict the values of the property plotted. it should
        be a 2-tuple, where the first value is a str giving the property
        to restrict, and the second is a list giving the values to
        restrict to (e.g., `('varea', [1,2,3])`). see
        neuropythy.cortex_plot's docstring for more details. If None,
        will plot everything

    """
    sub = ny.freesurfer_subject(freesurfer_sub)
    if isinstance(plot_property, dict):
        if len(plot_property) != 2:
            raise Exception("plot_property must either be a str or a dict with left and right "
                            "hemis, but plot_property has %s items!" % len(plot_property))
        property_data = plot_property
        plot_property = 'plot_property'
        lh = sub.lh.with_prop(plot_property=property_data['lh'])
        rh = sub.rh.with_prop(plot_property=property_data['rh'])
    else:
        lh = sub.lh
        rh = sub.rh

    # prepare to create a flat map of the posterior and anterior views
    # of the brain
    map_projs_post = {h: ny.map_projection('occipital_pole', h, radius=np.pi/2)
                      for h in ['lh', 'rh']}
    map_projs_ante = {h: mp.copy(center=-mp.center, center_right=-mp.center_right)
                      for h, mp in map_projs_post.items()}
    # flatten the surfaces
    flat_maps = [map_projs_post['lh'](lh), map_projs_post['rh'](rh),
                 map_projs_ante['lh'](lh), map_projs_ante['rh'](rh)]

    fig, axes = plt.subplots(2, 2, figsize=(7.5, 7.5), dpi=72*4)
    for ax, m in zip(axes.flatten(), flat_maps):
        ny.cortex_plot(m, axes=ax, color=plot_property, cmap='hot', mask=mask)
        ax.axis('off')
    fig.subplots_adjust(0, 0, 1, 1, 0, 0)
    if output_path is not None:
        fig.savefig(output_path)
    return fig


def voxel_property_plot(first_level_df, plot_property='precision', figsize=(10, 10),
                        df_filter_string='drop_voxels_with_any_negative_amplitudes,drop_voxels_near_border'):
    """Plot a voxel property (as size and color) on polar plot.

    Must be a property that each voxel has a unique value for (like precision);
    if it's a property that voxel shav emultiple values for (like
    amplitude_estimate), this plot will be misleading, because we drop all rows
    that have duplicate values for voxel

    df_filter_string can be used to filter the voxels we examine, so
    that we look only at those voxels that the model was fit to

    Parameters
    ----------
    first_level_df : pd.DataFrame
        DataFrame containing the outputs of first level analysis. Contains
        voxels with their angle, eccentricity, and several properties
    plot_property : str, optional
        str with the voxel property to plot. must be a column in first_level_df
    figsize : tuple, optional
        size of the plot to create
    df_filter_string : str or None, optional
        a str specifying how to filter the voxels in the dataset. see
        the docstrings for sfp.model.FirstLevelDataset and
        sfp.model.construct_df_filter for more details. If None, we
        won't filter. Should probably use the default, which is what all
        models are trained using.

    Returns
    -------
    fig : plt.figure
        matplotlib figure containing thhe plot

    """
    if df_filter_string is not None:
        df_filter = sfp_model.construct_df_filter(df_filter_string)
        first_level_df = df_filter(first_level_df).reset_index()
    voxels = first_level_df.drop_duplicates('voxel')
    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection='polar')
    size = voxels[plot_property].values.copy()
    while size.max() < 50:
        size *= 10
    c = ax.scatter(voxels.angle.values, voxels.eccen.values,
                   c=voxels[plot_property].values,
                   alpha=.75, s=size)
    ax.set(ylim=(0, 12.5))
    plt.colorbar(c)
    return fig


def voxel_property_joint(first_level_df, plot_kind='hex',
                         plot_properties=['eccen', 'precision'],
                         df_filter_string='drop_voxels_with_any_negative_amplitudes,drop_voxels_near_border',
                         **kwargs):
    """Plot a joint distribution plot (sns.jointplot) of two voxel properties.

    Must be a property that each voxel has a unique value for (like precision);
    if it's a property that voxel shav emultiple values for (like
    amplitude_estimate), this plot will be misleading, because we drop all rows
    that have duplicate values for voxel

    df_filter_string can be used to filter the voxels we examine, so
    that we look only at those voxels that the model was fit to

    Parameters
    ----------
    first_level_df : pd.DataFrame
        DataFrame containing the outputs of first level analysis. Contains
        voxels with their angle, eccentricity, and several properties
    plot_properties : list, optional
        list of strs, each of which is a the voxel property to plot and thus
        must be a column in first_level_df
    plot_kind : str, optional
        type of plot to use for joint plot. see sns.jointplot docstring for
        details
    df_filter_string : str or None, optional
        a str specifying how to filter the voxels in the dataset. see
        the docstrings for sfp.model.FirstLevelDataset and
        sfp.model.construct_df_filter for more details. If None, we
        won't filter. Should probably use the default, which is what all
        models are trained using.
    kwargs :
        passed to sns.jointplot

    Returns
    -------
    g : sns.JointGrid
        JointGrid containing the figure with the plot

    """
    if df_filter_string is not None:
        df_filter = sfp_model.construct_df_filter(df_filter_string)
        first_level_df = df_filter(first_level_df).reset_index()
    voxels = first_level_df.drop_duplicates('voxel')
    g = sns.jointplot(x=plot_properties[0], y=plot_properties[1], data=voxels,
                      kind=plot_kind, **kwargs)
    return g


def _parse_save_path_for_kwargs(save_path):
    kwargs = dict(i.split('=') for i in save_path.split('_'))
    # we know all are ints
    return dict(({'bootstrap': 'bootstrap_num'}.get(k, k), int(v)) for k, v in kwargs.items())


if __name__ == '__main__':
    class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter):
        pass
    parser = argparse.ArgumentParser(
        formatter_class=CustomFormatter,
        description=("Creates the descriptive plots for one first level results dataframe")
        )
    parser.add_argument("dataframe_path",
                        help=("path to first level results or tuning curves dataframe. we'll "
                              "attempt to find the other dataframe as well."))
    parser.add_argument("stim_dir", help="path to directory containing stimuli")
    parser.add_argument("--plot_to_make", default=None, nargs='*',
                        help=("Which plots to create. If none, will create all. Possible options: "
                              "localsf (plotting.local_spatial_frequency), stim_prop (plotting."
                              "stimuli_properties), data (plotting.plot_data), "
                              "tuning_curves_check_varea={v}[_bootstrap={b:02d}] (plotting."
                              "check_tuning_curves; requires tuning curve dataframe), "
                              "hypotheses_data_varea={v} (plotting.check_hypotheses_with_data; "
                              "requires tuning curve dataframe), or tuning_params "
                              "(plotting.tuning_params; requires tuning curve dataframe)"))
    args = vars(parser.parse_args())
    d = utils.create_data_dict(args['dataframe_path'], args['stim_dir'])
    first_level_save_stem = d['df_filename'].replace('.csv', '')
    if 'tuning_df' in d.keys():
        tuning_save_stem = d['tuning_df_filename'].replace('.csv', '')
        tuning_df_present = True
    else:
        tuning_df_present = False
    if args['plot_to_make'] is None:
        local_spatial_frequency(d['df'], first_level_save_stem+"_localsf.svg")
        stimuli_properties(d['df'], first_level_save_stem+"_stim_prop.svg")
        plot_data(d['df'], save_path=first_level_save_stem+'_data.svg')
        if tuning_df_present:
            check_tuning_curves(d['tuning_df'], tuning_save_stem+"_tuning_curves_check_%s.svg")
            check_hypotheses_with_data(d['tuning_df'], tuning_save_stem+"_hypotheses_data_%s.svg")
            tuning_params(d['tuning_df'], tuning_save_stem+"_tuning_params.svg")
        else:
            warnings.warn("Unable to create tuning curves, hypotheses check, or tuning param plots"
                          " because tuning curve df hasn't been created!")
    else:
        for p in args['plot_to_make']:
            if 'localsf' == p:
                local_spatial_frequency(d['df'], first_level_save_stem+"_localsf.svg")
            elif 'stim_prop' == p:
                stimuli_properties(d['df'], first_level_save_stem+"_stim_prop.svg")
            elif 'tuning_curves_check' in p:
                if tuning_df_present:
                    p_kwargs = _parse_save_path_for_kwargs(p.replace('tuning_curves_check_', ''))
                    check_tuning_curves(d['tuning_df'], tuning_save_stem+"_tuning_curves_check_%s.svg",
                                        **p_kwargs)
                else:
                    raise Exception("Unable to create tuning curves plot because tuning curve df "
                                    "hasn't been created!")
            elif 'data' == p:
                plot_data(d['df'], save_path=first_level_save_stem+'_data.svg')
            elif 'hypotheses_data' in p:
                if tuning_df_present:
                    p_kwargs = _parse_save_path_for_kwargs(p.replace('hypotheses_data_', ''))
                    check_hypotheses_with_data(d['tuning_df'], tuning_save_stem+"_hypotheses_data_%s.svg",
                                               **p_kwargs)
                else:
                    raise Exception("Unable to create hypotheses check with data plot because "
                                    "tuning curve df hasn't been created!")
            elif 'tuning_params' == p:
                if tuning_df_present:
                    tuning_params(d['tuning_df'], tuning_save_stem+"_tuning_params.svg")
                else:
                    raise Exception("Unable to create tuning params plot because "
                                    "tuning curve df hasn't been created!")
            else:
                raise Exception("Don't know how to make plot %s!" % p)
