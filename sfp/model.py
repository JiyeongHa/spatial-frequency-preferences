#!/usr/bin/python
"""2d tuning model
"""
import matplotlib as mpl
# we do this because sometimes we run this without an X-server, and this backend doesn't need
# one. We set warn=False because the notebook uses a different backend and will spout out a big
# warning to that effect; that's unnecessarily alarming, so we hide it.
mpl.use('svg', warn=False)
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import time
import torch
import warnings
import argparse
import itertools
import functools
from torch.utils import data as torchdata


def reduce_num_voxels(df, n_voxels=200):
    """drop all but the first n_voxels

    this is just to speed things up for testing, it obviously shouldn't be used if you are actually
    trying to fit the data
    """
    return df[df.voxel < n_voxels]


def drop_voxels_with_negative_amplitudes(df):
    """drop all voxels that have at least one negative amplitude
    """
    try:
        df = df.groupby('voxel').filter(lambda x: (x.amplitude_estimate_normed >= 0).all())
    except AttributeError:
        df = df.groupby('voxel').filter(lambda x: (x.amplitude_estimate_median_normed >= 0).all())
    return df


def drop_voxels_near_border(df, inner_border=.96, outer_border=12):
    """drop all voxels whose pRF center is one sigma away form the border

    where the sigma is the sigma of the Gaussian pRF
    """
    df = df.groupby('voxel').filter(lambda x: (x.eccen + x.sigma <= outer_border).all())
    df = df.groupby('voxel').filter(lambda x: (x.eccen - x.sigma >= inner_border).all())
    return df


def _cast_as_tensor(x):
    if type(x) == pd.Series:
        x = x.values
    return torch.tensor(x, dtype=torch.float64)


def _cast_as_param(x, requires_grad=True):
    return torch.nn.Parameter(_cast_as_tensor(x), requires_grad=requires_grad)


def _cast_args_as_tensors(args, on_cuda=False):
    return_args = []
    for v in args:
        if not torch.is_tensor(v):
            v = _cast_as_tensor(v)
        if on_cuda:
            v = v.cuda()
        return_args.append(v)
    return return_args


def _check_and_reshape_tensors(x, y):
    if (x.ndimension() == 1 and y.ndimension() == 1) and (x.shape != y.shape):
        x = x.repeat(len(y), 1)
        y = y.repeat(x.shape[1], 1).transpose(0, 1)
    return x, y


class FirstLevelDataset(torchdata.Dataset):
    """Dataset for first level results

    the __getitem__ method here returns all (48) values for a single voxel, so keep that in mind
    when setting batch size. this is done because (in the loss function) we normalize the
    predictions and target so that that vector of length 48 has a norm of one.

    In addition the features and targets, we also return the precision

    df_filter: function or None. If not None, a function that takes a dataframe as input and
    returns one (most likely, a subset of the original) as output. See
    `drop_voxels_with_negative_amplitudes` for an example.

    stimulus_class: list of ints or None. What subset of the stimulus_class should be used. these
    are numbers between 0 and 47 (inclusive) and then the dataset will only include data from those
    stimulus classes. this is used for cross-validation purposes (i.e., train on 0 through 46, test
    on 47).
    """
    def __init__(self, df_path, device, df_filter=None, stimulus_class=None):
        df = pd.read_csv(df_path)
        if df_filter is not None:
            # we want the index to be reset so we can use iloc in get_single_item below. this
            # ensures that iloc and loc will return the same thing, which isn't otherwise the
            # case. and we want them to be the same because Dataloader assumes iloc but our custom
            # get_voxel needs loc.
            df = df_filter(df).reset_index()
        # in order to make sure that we can iterate through the dataset (as dataloader does), we
        # need to create a new "voxel" column. this column just relabels the voxel column, running
        # from 0 to df.voxel.nunique() while ensuring that voxel identity is preserved. if
        # df_filter is None, df.voxel_reindexed should just be a copy of df.voxel
        new_idx = pd.Series(range(df.voxel.nunique()), df.voxel.unique())
        df = df.set_index('voxel')
        df['voxel_reindexed'] = new_idx
        if stimulus_class is not None:
            df = df[df.stimulus_class.isin(stimulus_class)]
        if df.empty:
            raise Exception("Dataframe is empty!")
        self.df = df.reset_index()
        self.device = device
        self.df_path = df_path
        self.stimulus_class = df.stimulus_class.unique()

    def get_single_item(self, idx):
        row = self.df.iloc[idx]
        vals = row[['local_sf_magnitude', 'local_sf_xy_direction', 'eccen', 'angle']].values
        feature = _cast_as_tensor(vals.astype(float))
        try:
            target = _cast_as_tensor(row['amplitude_estimate'])
        except KeyError:
            target = _cast_as_tensor(row['amplitude_estimate_median'])
        precision = _cast_as_tensor(row['precision'])
        return (feature.to(self.device), target.to(self.device), precision.to(self.device))

    def __getitem__(self, idx):
        vox_idx = self.df[self.df.voxel_reindexed == idx].index
        return self.get_single_item(vox_idx)

    def get_voxel(self, idx):
        vox_idx = self.df[self.df.voxel == idx].index
        return self.get_single_item(vox_idx)

    def __len__(self):
        return self.df.voxel.nunique()


class LogGaussianDonut(torch.nn.Module):
    """simple LogGaussianDonut in pytorch

    orientation_type, eccentricity_type, vary_amplitude: together specify what
    kind of model to train

    orientation_type: {iso, absolute, relative, full}.
    - iso: model is isotropic, predictions identical for all orientations.
    - absolute: model can fit differences in absolute orientation, that is, in Cartesian
      coordinates, such that sf_angle=0 correponds to "to the right"
    - relative: model can fit differences in relative orientation, that is, in retinal polar
      coordinates, such that sf_angle=0 corresponds to "away from the fovea"
    - full: model can fit differences in both absolute and relative orientations

    eccentricity_type: {scaling, constant, full}.
    - scaling: model's relationship between preferred period and eccentricity is exactly scaling,
      that is, the preferred period is equal to the eccentricity.
    - constant: model's relationship between preferred period and eccentricity is exactly constant,
      that is, it does not change with eccentricity but is flat.
    - full: model discovers the relationship between eccentricity and preferred period, though it
      is constrained to be linear (i.e., model solves for a and b in $period = a * eccentricity +
      b$)

    vary_amplitude: boolean. whether to allow the model to fit the parameters that control
    amplitude as a function of orientation (whether this depends on absolute orientation, relative
    orientation, or both depends on the value of `orientation_type`)

    all other parameters are initial values. whether they will be fit or not (i.e., whether they
    have `requires_grad=True`) depends on the values of `orientation_type`, `eccentricity_type` and
    `vary_amplitude`

    when you call this model, sf_angle should be the (absolute) orientation of the grating, so that
    sf_angle=0 corresponds to "to the right". That is, regardless of whether the model considers
    the absolute orientation, relative orientation, neither or both to be important, you always
    call it with the absolute orientation.

    """
    def __init__(self, orientation_type='iso', eccentricity_type='full', vary_amplitude=True,
                 sigma=.4, sf_ecc_slope=1, sf_ecc_intercept=0, abs_mode_cardinals=0,
                 abs_mode_obliques=0, rel_mode_cardinals=0, rel_mode_obliques=0,
                 abs_amplitude_cardinals=0, abs_amplitude_obliques=0, rel_amplitude_cardinals=0,
                 rel_amplitude_obliques=0):
        super().__init__()
        train_kwargs = {}
        kwargs = {}
        for ori, param, angle in itertools.product(['abs', 'rel'], ['mode', 'amplitude'],
                                                   ['cardinals', 'obliques']):
            train_kwargs['%s_%s_%s' % (ori, param, angle)] = True
            kwargs['%s_%s_%s' % (ori, param, angle)] = eval('%s_%s_%s' % (ori, param, angle))
        for var in ['slope', 'intercept']:
            train_kwargs['sf_ecc_%s' % var] = True
            kwargs['sf_ecc_%s' % var] = eval("sf_ecc_%s" % var)
        if orientation_type in ['relative', 'iso']:
            for param, angle in itertools.product(['mode', 'amplitude'],
                                                  ['cardinals', 'obliques']):
                if kwargs['abs_%s_%s' % (param, angle)] != 0:
                    warnings.warn("When orientation_type is %s, all absolute variables must"
                                  " be 0, correcting this..." % orientation_type)
                    kwargs['abs_%s_%s' % (param, angle)] = 0
                train_kwargs['abs_%s_%s' % (param, angle)] = False
        if orientation_type in ['absolute', 'iso']:
            for param, angle in itertools.product(['mode', 'amplitude'],
                                                  ['cardinals', 'obliques']):
                if kwargs['rel_%s_%s' % (param, angle)] != 0:
                    warnings.warn("When orientation_type is %s, all relative variables must"
                                  " be 0, correcting this..." % orientation_type)
                    kwargs['rel_%s_%s' % (param, angle)] = 0
                train_kwargs['rel_%s_%s' % (param, angle)] = False
        if orientation_type not in ['relative', 'absolute', 'iso', 'full']:
            raise Exception("Don't know how to handle orientation_type %s!" % orientation_type)
        self.orientation_type = orientation_type
        if not vary_amplitude:
            amp_vary_label = 'constant'
            for ori, angle in itertools.product(['abs', 'rel'], ['cardinals', 'obliques']):
                if kwargs['%s_amplitude_%s' % (ori, angle)] != 0:
                    warnings.warn("When vary_amplitude is False, all amplitude variables must"
                                  " be 0, correcting this...")
                    kwargs['%s_amplitude_%s' % (ori, angle)] = 0
                train_kwargs['%s_amplitude_%s' % (ori, angle)] = False
        else:
            amp_vary_label = 'vary'
        if eccentricity_type == 'scaling':
            if kwargs['sf_ecc_intercept'] != 0:
                warnings.warn("When eccentricity_type is scaling, sf_ecc_intercept must be 0! "
                              "correcting...")
                kwargs['sf_ecc_intercept'] = 0
            train_kwargs['sf_ecc_intercept'] = False
        elif eccentricity_type == 'constant':
            if kwargs['sf_ecc_slope'] != 0:
                warnings.warn("When eccentricity_type is constant, sf_ecc_slope must be 0! "
                              "correcting...")
                kwargs['sf_ecc_slope'] = 0
            train_kwargs['sf_ecc_slope'] = False
        elif eccentricity_type != 'full':
            raise Exception("Don't know how to handle eccentricity_type %s!" % eccentricity_type)
        self.eccentricity_type = eccentricity_type
        self.vary_amplitude = vary_amplitude
        self.model_type = '%s_donut_%s_amps-%s' % (eccentricity_type, orientation_type,
                                                   amp_vary_label)
        self.sigma = _cast_as_param(sigma)

        self.abs_amplitude_cardinals = _cast_as_param(kwargs['abs_amplitude_cardinals'],
                                                      train_kwargs['abs_amplitude_cardinals'])
        self.abs_amplitude_obliques = _cast_as_param(kwargs['abs_amplitude_obliques'],
                                                     train_kwargs['abs_amplitude_obliques'])
        self.rel_amplitude_cardinals = _cast_as_param(kwargs['rel_amplitude_cardinals'],
                                                      train_kwargs['rel_amplitude_cardinals'])
        self.rel_amplitude_obliques = _cast_as_param(kwargs['rel_amplitude_obliques'],
                                                     train_kwargs['rel_amplitude_obliques'])
        self.abs_mode_cardinals = _cast_as_param(kwargs['abs_mode_cardinals'],
                                                 train_kwargs['abs_mode_cardinals'])
        self.abs_mode_obliques = _cast_as_param(kwargs['abs_mode_obliques'],
                                                train_kwargs['abs_mode_obliques'])
        self.rel_mode_cardinals = _cast_as_param(kwargs['rel_mode_cardinals'],
                                                 train_kwargs['rel_mode_cardinals'])
        self.rel_mode_obliques = _cast_as_param(kwargs['rel_mode_obliques'],
                                                train_kwargs['rel_mode_obliques'])
        self.sf_ecc_slope = _cast_as_param(kwargs['sf_ecc_slope'],
                                           train_kwargs['sf_ecc_slope'])
        self.sf_ecc_intercept = _cast_as_param(kwargs['sf_ecc_intercept'],
                                               train_kwargs['sf_ecc_intercept'])

    def __str__(self):
        # so we can see the parameters
        return ("{0}(sigma: {1:.03f}, sf_ecc_slope: {2:.03f}, sf_ecc_intercept: {3:.03f}, "
                "abs_amplitude_cardinals: {4:.03f}, abs_amplitude_obliques: {5:.03f}, "
                "abs_mode_cardinals: {6:.03f}, abs_mode_obliques: {7:.03f}, "
                "rel_amplitude_cardinals: {8:.03f}, rel_amplitude_obliques: {9:.03f}, "
                "rel_mode_cardinals: {10:.03f}, rel_mode_obliques: {11:.03f})").format(
                    type(self).__name__, self.sigma, self.sf_ecc_slope, self.sf_ecc_intercept,
                    self.abs_amplitude_cardinals, self.abs_amplitude_obliques,
                    self.abs_mode_cardinals, self.abs_mode_obliques, self.rel_amplitude_cardinals,
                    self.rel_amplitude_obliques, self.rel_mode_cardinals, self.rel_mode_obliques)

    def __repr__(self):
        return self.__str__()

    def _create_mag_angle(self, extent=(-10, 10), n_samps=1001):
        x = torch.linspace(extent[0], extent[1], n_samps)
        x, y = torch.meshgrid(x, x)
        r = torch.sqrt(torch.pow(x, 2) + torch.pow(y, 2))
        th = torch.atan2(y, x)
        return r, th

    def create_image(self, vox_ecc, vox_angle, extent=None, n_samps=1001):
        r, th = self._create_mag_angle(extent, n_samps)
        return self.evaluate(r, th, vox_ecc, vox_angle)

    def preferred_period(self, sf_angle, vox_ecc, vox_angle):
        """return preferred period for specified voxel at given orientation
        """
        sf_angle, vox_ecc, vox_angle = _cast_args_as_tensors([sf_angle, vox_ecc, vox_angle],
                                                             self.sigma.is_cuda)
        # we can allow up to two of these variables to be non-singletons.
        if sf_angle.ndimension() == 1 and vox_ecc.ndimension() == 1 and vox_angle.ndimension() == 1:
            # if this is False, then all of them are the same shape and we have no issues
            if sf_angle.shape != vox_ecc.shape != vox_angle.shape:
                raise Exception("Only two of these variables can be non-singletons!")
        else:
            sf_angle, vox_ecc = _check_and_reshape_tensors(sf_angle, vox_ecc)
            vox_ecc, vox_angle = _check_and_reshape_tensors(vox_ecc, vox_angle)
            sf_angle, vox_angle = _check_and_reshape_tensors(sf_angle, vox_angle)
        rel_sf_angle = sf_angle - vox_angle
        eccentricity_effect = self.sf_ecc_slope * vox_ecc + self.sf_ecc_intercept
        orientation_effect = (1 + self.abs_mode_cardinals * torch.cos(2 * sf_angle) +
                              self.abs_mode_obliques * torch.cos(4 * sf_angle) +
                              self.rel_mode_cardinals * torch.cos(2 * rel_sf_angle) +
                              self.rel_mode_obliques * torch.cos(4 * rel_sf_angle))
        return torch.clamp(eccentricity_effect * orientation_effect, min=1e-6)

    def preferred_sf(self, sf_angle, vox_ecc, vox_angle):
        return 1. / self.preferred_period(sf_angle, vox_ecc, vox_angle)

    def max_amplitude(self, sf_angle, vox_angle):
        sf_angle, vox_angle = _cast_args_as_tensors([sf_angle, vox_angle], self.sigma.is_cuda)
        sf_angle, vox_angle = _check_and_reshape_tensors(sf_angle, vox_angle)
        rel_sf_angle = sf_angle - vox_angle
        amplitude = (1 + self.abs_amplitude_cardinals * torch.cos(2*sf_angle) +
                     self.abs_amplitude_obliques * torch.cos(4*sf_angle) +
                     self.rel_amplitude_cardinals * torch.cos(2*rel_sf_angle) +
                     self.rel_amplitude_obliques * torch.cos(4*rel_sf_angle))
        return torch.clamp(amplitude, min=1e-6)

    def evaluate(self, sf_mag, sf_angle, vox_ecc, vox_angle):
        sf_mag, = _cast_args_as_tensors([sf_mag], self.sigma.is_cuda)
        # if ecc_effect is 0 or below, then log2(ecc_effect) is infinity or undefined
        # (respectively). to avoid that, we clamp it 1e-6. in practice, if a voxel ends up here
        # that means the model predicts 0 response for it.
        preferred_period = self.preferred_period(sf_angle, vox_ecc, vox_angle)
        pdf = torch.exp(-((torch.log2(sf_mag) + torch.log2(preferred_period))**2) /
                        (2*self.sigma**2))
        amplitude = self.max_amplitude(sf_angle, vox_angle)
        return amplitude * pdf

    def forward(self, spatial_frequency_magnitude, spatial_frequency_theta, voxel_eccentricity,
                voxel_angle):
        """
        In the forward function we accept a Tensor of input data and we must return
        a Tensor of output data. We can use Modules defined in the constructor as
        well as arbitrary operators on Tensors.
        """
        return self.evaluate(spatial_frequency_magnitude, spatial_frequency_theta,
                             voxel_eccentricity, voxel_angle)


def show_image(donut, voxel_eccentricity=1, voxel_angle=0, extent=(-5, 5), n_samps=1001,
               cmap="Reds", show_colorbar=True, ax=None, **kwargs):
    """wrapper function to plot the image from a given donut

    This shows the spatial frequency selectivity implied by the donut at a given voxel eccentricity
    and angle, if appropriate (eccentricity and angle ignored if donut is ConstantLogGuassianDonut)

    donut: a LogGaussianDonut

    extent: 2-tuple of floats. the range of spatial frequencies to visualize `(min, max)`. this
    will be the same for x and y
    """
    if ax is None:
        plt.imshow(
            donut.create_image(voxel_eccentricity, voxel_angle, extent, n_samps=n_samps).detach(),
            extent=(extent[0], extent[1], extent[0], extent[1]), cmap=cmap,
            origin='lower', **kwargs)
        ax = plt.gca()
    else:
        ax.imshow(
            donut.create_image(voxel_eccentricity, voxel_angle, extent, n_samps=n_samps).detach(),
            extent=(extent[0], extent[1], extent[0], extent[1]), cmap=cmap,
            origin='lower', **kwargs)
    ax.axes.xaxis.set_visible(False)
    ax.axes.yaxis.set_visible(False)
    ax.set_frame_on(False)
    if show_colorbar:
        plt.colorbar()
    return ax


def construct_loss_df(loss_history, subset='train'):
    """constructs loss dataframe from array of lost history

    loss_history: 2d list or array, as constructed in `train_model`, n_epochs by batch_size
    """
    loss_df = pd.DataFrame(np.array(loss_history))
    loss_df = pd.melt(loss_df.reset_index(), id_vars='index', var_name='batch_num',
                      value_name='loss')
    loss_df['data_subset'] = subset
    return loss_df.rename(columns={'index': 'epoch_num'})


def check_performance(trained_model, dataset, test_dataset=None):
    """check performance of trained_model for each voxel in the dataset

    this assumes both model and dataset are on the same device
    """
    performance = []
    for i in dataset.df.voxel.unique():
        features, targets, precision = dataset.get_voxel(i)
        predictions = trained_model(*features.transpose(1, 0))
        if test_dataset is not None:
            test_features, test_target, test_precision = test_dataset.get_voxel(i)
            test_predictions = trained_model(*test_features.transpose(1, 0))
            cv_loss = weighted_normed_loss(test_predictions, test_target, test_precision,
                                           torch.cat([test_predictions, predictions]),
                                           torch.cat([test_target, targets])).item()
        else:
            cv_loss = None
        corr = np.corrcoef(targets.cpu().detach().numpy(), predictions.cpu().detach().numpy())
        loss = weighted_normed_loss(predictions, targets, precision).item()
        performance.append(pd.DataFrame({'voxel': i, 'stimulus_class': range(len(targets)),
                                         'model_prediction_correlation': corr[0, 1],
                                         'model_prediction_loss': loss,
                                         'model_predictions': predictions.cpu().detach().numpy(),
                                         'model_prediction_cv_loss': cv_loss}))
    return pd.concat(performance)


def combine_first_level_df_with_performance(first_level_df, performance_df):
    """combine results_df and performance_df, along the voxel, producing results_df
    """
    results_df = first_level_df.set_index(['voxel', 'stimulus_class'])
    performance_df = performance_df.set_index(['voxel', 'stimulus_class'])
    results_df = results_df.join(performance_df).reset_index()
    return results_df.reset_index()


def construct_dfs(model, dataset, train_loss_history, max_epochs, batch_size, learning_rate,
                  train_thresh, current_epoch, start_time, test_loss_history=None,
                  test_dataset=None):
    """construct the loss and results dataframes and add metadata
    """
    loss_df = construct_loss_df(train_loss_history)
    if test_loss_history is not None:
        loss_df = pd.concat([loss_df, construct_loss_df(test_loss_history, 'test')])
    loss_df['max_epochs'] = max_epochs
    loss_df['batch_size'] = batch_size
    loss_df['learning_rate'] = learning_rate
    loss_df['train_thresh'] = train_thresh
    loss_df['epochs_trained'] = current_epoch
    loss_df['time_elapsed'] = time.time() - start_time
    # we reload the first level dataframe because the one in dataset may be filtered in some way
    results_df = combine_first_level_df_with_performance(pd.read_csv(dataset.df_path),
                                                         check_performance(model, dataset,
                                                                           test_dataset))
    if type(model) == torch.nn.DataParallel:
        # in this case, we need to access model.module in order to get the various custom
        # attributes we set in our LogGaussianDonut
        model = model.module
    results_df['fit_model_type'] = model.model_type
    loss_df['fit_model_type'] = model.model_type
    # this is the case if the data is simulated
    for col in ['true_model_type', 'noise_level', 'noise_source_df']:
        if col in results_df.columns:
            loss_df[col] = results_df[col].unique()[0]
    for name, val in model.named_parameters():
        results_df['fit_model_%s' % name] = val.cpu().detach().numpy()
    results_df['epochs_trained'] = current_epoch
    results_df['batch_size'] = batch_size
    results_df['learning_rate'] = learning_rate
    return loss_df, results_df


def save_outputs(model, loss_df, results_df, save_path_stem):
    """save outputs (if save_path_stem is not None)

    results_df can be None, in which case we don't save it.
    """
    if type(model) == torch.nn.DataParallel:
        # in this case, we need to access model.module in order to just save the model
        model = model.module
    if save_path_stem is not None:
        torch.save(model.state_dict(), save_path_stem + "_model.pt")
        loss_df.to_csv(save_path_stem + "_loss.csv", index=False)
        if results_df is not None:
            results_df.to_csv(save_path_stem + "_results_df.csv", index=False)


def weighted_normed_loss(predictions, target, precision, predictions_for_norm=None,
                         target_for_norm=None):
    """takes in the predictions and target

    note all of these must be tensors, not numpy arrays

    predictions_for_norm, target_for_norm: normally, this should be called such that predictions
    and target each contain all the values for the voxels investigated. however, during
    cross-validation, predictions and target will contain a subset of the stimulus classes, so we
    need to pass the predictions and targets for all stimulus classes as well in order to normalize
    them properly (for an intuition as to why this is important, consider the extreme case: if both
    predictions and target have length 1 and are normalized with respect to themselves, the loss
    will always be 0)
    """
    # we occasionally have an issue where the predictions are really small (like 1e-200), which
    # gives us a norm of 0 and thus a normed_predictions of infinity, and thus an infinite loss.
    # the point of renorming is that multiplying by a scale factor won't change our loss, so we do
    # that here to avoid this issue
    if 0 in predictions.norm(2, -1, True):
        predictions = predictions * 1e100
    if predictions_for_norm is None:
        assert target_for_norm is None, "Both target_for_norm and predictions_for_norm must be unset"
        predictions_for_norm = predictions
        target_for_norm = target
    # we norm / average along the last dimension, since that means we do it across all stimulus
    # classes for a given voxel. we don't know whether these tensors will be 1d (single voxel, as
    # returned by our FirstLevelDataset) or 2d (multiple voxels, as returned by the DataLoader)
    normed_predictions = predictions / predictions_for_norm.norm(2, -1, True)
    normed_target = target / target_for_norm.norm(2, -1, True)
    # this isn't really necessary (all the values along that dimension should be identical, based
    # on how we calculated it), but just in case. and this gets it in the right shape
    precision = precision.mean(-1, True)
    squared_error = precision * (normed_predictions - normed_target)**2
    return squared_error.mean()


def train_model(model, dataset, max_epochs=5, batch_size=1, train_thresh=1e-8,
                learning_rate=1e-2, save_path_stem=None):
    """train the model
    """
    training_parameters = [p for p in model.parameters() if p.requires_grad]
    # AMSGrad argument here means we use a revised version that handles a bug people found where
    # it doesn't necessarily converge
    optimizer = torch.optim.Adam(training_parameters, lr=learning_rate, amsgrad=True)
    dataloader = torchdata.DataLoader(dataset, batch_size)
    loss_history = []
    start_time = time.time()
    for t in range(max_epochs):
        loss_history.append([])
        for i, (features, target, precision) in enumerate(dataloader):
            # these transposes get features from the dimensions (voxels, stimulus class, features)
            # into (features, voxels, stimulus class) so that the predictions are shape (voxels,
            # stimulus class), just like the targets are
            predictions = model(*features.transpose(2, 0).transpose(2, 1))
            loss = weighted_normed_loss(predictions, target, precision)
            loss_history[t].append(loss.item())
            if np.isnan(loss.item()) or np.isinf(loss.item()):
                print("Loss is nan or inf on epoch %s, batch %s! We won't update parameters on "
                      "this batch" % (t, i))
                print("Predictions are: %s" % predictions.detach())
                continue
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        if (t % 100) == 0:
            loss_df, results_df = construct_dfs(model, dataset, loss_history, max_epochs,
                                                batch_size, learning_rate, train_thresh, t,
                                                start_time)
            save_outputs(model, loss_df, results_df, save_path_stem)
        print("Average loss on epoch %s: %s" % (t, np.mean(loss_history[-1])))
        print(model)
        if len(loss_history) > 3:
            if ((np.abs(np.mean(loss_history[-1]) - np.mean(loss_history[-2])) < train_thresh) and
                (np.abs(np.mean(loss_history[-2]) - np.mean(loss_history[-3])) < train_thresh) and
                (np.abs(np.mean(loss_history[-3]) - np.mean(loss_history[-4])) < train_thresh)):
                print("Epoch loss appears to have stopped declining, so we stop training")
                break
    loss_df, results_df = construct_dfs(model, dataset, loss_history, max_epochs, batch_size,
                                        learning_rate, train_thresh, t, start_time)
    return model, loss_df, results_df


def train_model_traintest(model, train_dataset, test_dataset, full_dataset, max_epochs=5,
                          batch_size=1, train_thresh=1e-8, learning_rate=1e-2,
                          save_path_stem=None):
    """train the model with separate train and test sets
    """
    training_parameters = [p for p in model.parameters() if p.requires_grad]
    # AMSGrad argument here means we use a revised version that handles a bug people found where
    # it doesn't necessarily converge
    optimizer = torch.optim.Adam(training_parameters, lr=learning_rate, amsgrad=True)
    train_dataloader = torchdata.DataLoader(train_dataset, batch_size)
    test_dataloader = torchdata.DataLoader(test_dataset, batch_size)
    train_loss_history = []
    test_loss_history = []
    start_time = time.time()
    for t in range(max_epochs):
        train_loss_history.append([])
        for i, (train_stuff, test_stuff) in enumerate(zip(train_dataloader, test_dataloader)):
            features, target, precision = train_stuff
            test_features, test_target, _ = test_stuff
            # these transposes get features from the dimensions (voxels, stimulus class, features)
            # into (features, voxels, stimulus class) so that the predictions are shape (voxels,
            # stimulus class), just like the targets are
            predictions = model(*features.transpose(2, 0).transpose(2, 1))
            test_predictions = model(*test_features.transpose(2, 0).transpose(2, 1))
            loss = weighted_normed_loss(predictions, target, precision,
                                        torch.cat([test_predictions, predictions], 1),
                                        torch.cat([test_target, target], 1))
            train_loss_history[t].append(loss.item())
            if np.isnan(loss.item()) or np.isinf(loss.item()):
                print("Loss is nan or inf on epoch %s, batch %s! We won't update parameters on "
                      "this batch" % (t, i))
                print("Predictions are: %s" % predictions.detach())
                continue
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        model.eval()
        test_loss_history.append([])
        for v in test_dataset.df.voxel.unique():
            test_features, test_target, test_precision = test_dataset.get_voxel(v)
            train_features, train_target, _ = train_dataset.get_voxel(v)
            test_predictions = model(*test_features.transpose(1, 0))
            train_predictions = model(*train_features.transpose(1, 0))
            loss = weighted_normed_loss(test_predictions, test_target, test_precision,
                                        torch.cat([test_predictions, train_predictions]),
                                        torch.cat([test_target, train_target]))
            test_loss_history[t].append(loss.item())
        model.train()
        if (t % 100) == 0:
            loss_df, results_df = construct_dfs(model, full_dataset, train_loss_history,
                                                max_epochs, batch_size, learning_rate,
                                                train_thresh, t, start_time, test_loss_history,
                                                test_dataset)
            # don't save results_df when cross-validating
            save_outputs(model, loss_df, None, save_path_stem)
        print("Average train loss on epoch %s: %s" % (t, np.mean(train_loss_history[-1])))
        print("Average test loss on epoch %s: %s" % (t, np.mean(test_loss_history[-1])))
        print(model)
        if len(train_loss_history) > 3:
            if ((np.abs(np.mean(train_loss_history[-1]) - np.mean(train_loss_history[-2])) < train_thresh) and
                (np.abs(np.mean(train_loss_history[-2]) - np.mean(train_loss_history[-3])) < train_thresh) and
                (np.abs(np.mean(train_loss_history[-3]) - np.mean(train_loss_history[-4])) < train_thresh)):
                print("Training loss appears to have stopped declining, so we stop training")
                break
    loss_df, results_df = construct_dfs(model, full_dataset, train_loss_history, max_epochs,
                                        batch_size, learning_rate, train_thresh, t, start_time,
                                        test_loss_history, test_dataset)
    return model, loss_df, results_df


def main(model_orientation_type, model_eccentricity_type, model_vary_amplitude,
         first_level_results_path, random_seed=None, max_epochs=100, train_thresh=1e-8,
         batch_size=1, df_filter=None, learning_rate=1e-2, stimulus_class=None,
         save_path_stem="pytorch"):
    """create, train, and save a model on the given first_level_results dataframe

    model_orientation_type, model_eccentricity_type, model_vary_amplitude: together specify what
    kind of model to train

    model_orientation_type: {iso, absolute, relative, full}.
    - iso: model is isotropic, predictions identical for all orientations.
    - absolute: model can fit differences in absolute orientation, that is, in Cartesian
      coordinates, such that sf_angle=0 correponds to "to the right"
    - relative: model can fit differences in relative orientation, that is, in retinal polar
      coordinates, such that sf_angle=0 corresponds to "away from the fovea"
    - full: model can fit differences in both absolute and relative orientations

    model_eccentricity_type: {scaling, constant, full}.
    - scaling: model's relationship between preferred period and eccentricity is exactly scaling,
      that is, the preferred period is equal to the eccentricity.
    - constant: model's relationship between preferred period and eccentricity is exactly constant,
      that is, it does not change with eccentricity but is flat.
    - full: model discovers the relationship between eccentricity and preferred period, though it
      is constrained to be linear (i.e., model solves for a and b in $period = a * eccentricity +
      b$)

    model_vary_amplitude: boolean. whether to allow the model to fit the parameters that control
    amplitude as a function of orientation (whether this depends on absolute orientation, relative
    orientation, or both depends on the value of `model_orientation_type`)

    first_level_results_path: str. Path to the first level results dataframe containing the data to
    fit.

    random_seed: int or None. we initialize the model with random parameters in order to try and
    avoid local optima. we set the seed before generating all those random numbers.

    max_epochs: int. the max number of epochs to let the training run for. otherwise, we train
    until the loss changes by less than train_thresh for 3 epochs in a row.

    df_filter: function or None. If not None, a function that takes a dataframe as input and
    returns one (most likely, a subset of the original) as output. See
    `drop_voxels_with_negative_amplitudes` for an example.

    stimulus_class: list of ints or None. What subset of the stimulus_class should be used. these
    are numbers between 0 and 47 (inclusive) and then the dataset will only include data from those
    stimulus classes. this is used for cross-validation purposes (i.e., train on 0 through 46, test
    on 47).

    save_path_stem: string or None. a string to save the trained model and loss_df at (should have
    no extension because we'll add it ourselves). If None, will not save the output.

    """
    # when we fit the model, we want to randomly initialize its starting parameters (for a given
    # seed) in order to help avoid local optima.
    if random_seed is not None:
        np.random.seed(int(random_seed))
    # all the parameters are bounded below by 0. they're not bounded above by anything. However,
    # they will probably be small, so we use a max of 1 (things get weird when the orientation
    # effect parameters get too large).
    param_inits = np.random.uniform(0, 1, 11)
    model = LogGaussianDonut(model_orientation_type, model_eccentricity_type, model_vary_amplitude,
                             *param_inits)
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if torch.cuda.device_count() > 1 and batch_size > torch.cuda.device_count():
        model = torch.nn.DataParallel(model)
    model.to(device)
    dataset = FirstLevelDataset(first_level_results_path, device, df_filter)
    if stimulus_class is None:
        print("Beginning training!")
        # use all stimulus classes
        model, loss_df, results_df = train_model(model, dataset, max_epochs, batch_size,
                                                 train_thresh, learning_rate, save_path_stem)
        test_subset = 'none'
    else:
        df = pd.read_csv(first_level_results_path)
        all_stimulus_class = df.stimulus_class.unique()
        other_stimulus_class = [i for i in all_stimulus_class if i not in stimulus_class]
        # split into test and train
        if len(other_stimulus_class) > len(stimulus_class):
            # we assume that test set should be smaller than train
            train_dataset = FirstLevelDataset(first_level_results_path, device, df_filter,
                                              other_stimulus_class)
            test_dataset = FirstLevelDataset(first_level_results_path, device, df_filter,
                                             stimulus_class)
            test_subset = stimulus_class
        else:
            train_dataset = FirstLevelDataset(first_level_results_path, device, df_filter,
                                              stimulus_class)
            test_dataset = FirstLevelDataset(first_level_results_path, device, df_filter,
                                             other_stimulus_class)
            test_subset = other_stimulus_class
        print("Beginning training, treating stimulus classes %s as test "
              "set!" % test_subset)
        model, loss_df, results_df = train_model_traintest(model, train_dataset, test_dataset,
                                                           dataset, max_epochs, batch_size,
                                                           train_thresh, learning_rate,
                                                           save_path_stem)
    test_subset = str(test_subset).replace('[', '').replace(']', '')
    if len(test_subset) == 1:
        test_subset = int(test_subset)
    results_df['test_subset'] = test_subset
    loss_df['test_subset'] = test_subset
    print("Finished training!")
    if stimulus_class is None:
        save_outputs(model, loss_df, results_df, save_path_stem)
    else:
        save_outputs(model, loss_df, None, save_path_stem)
    model.eval()
    return model, loss_df, results_df


def construct_df_filter(df_filter_string):
    """construct df_filter from string (as used in our command-line parser)

    the string should be a single string containing at least one of the following, separated by
    commas: 'drop_voxels_with_negative_amplitudes', 'reduce_num_voxels:n' (where n is an integer),
    'None'. This will then construct the function that will chain them together in the order
    specified (if None is one of the entries, we will simply return None)
    """
    df_filters = []
    for f in df_filter_string.split(','):
        # this is a little bit weird, but it does what we want
        if f == 'drop_voxels_with_negative_amplitudes':
            df_filters.append(drop_voxels_with_negative_amplitudes)
        elif f == 'drop_voxels_near_border':
            df_filters.append(drop_voxels_near_border)
        elif f == 'None' or f == 'none':
            df_filters = [None]
            break
        elif f.startswith('reduce_num_voxels:'):
            n_voxels = int(f.split(':')[-1])
            df_filters.append(lambda x: reduce_num_voxels(x, n_voxels))
        else:
            raise Exception("Don't know what to do with df_filter %s" % f)
    if len(df_filters) > 1:
        # from
        # https://stackoverflow.com/questions/11736407/apply-list-of-functions-on-an-object-in-python#11736719
        # and in python 3, reduce is replaced with functools.reduce
        df_filter = lambda x: functools.reduce(lambda o, func: func(o), df_filters, x)
    else:
        df_filter = df_filters[0]
    return df_filter


class NewLinesHelpFormatter(argparse.HelpFormatter):
    # add empty line if help ends with \n
    def _split_lines(self, text, width):
        text = text.split('\n')
        lines = []
        for t in text:
            lines.extend(super()._split_lines(t, width))
        return lines


if __name__ == '__main__':
    class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                          NewLinesHelpFormatter):
        pass
    parser = argparse.ArgumentParser(
        formatter_class=CustomFormatter,
        description=("Load in the first level results Dataframe and train a 2d tuning model on it"
                     ". Will save the model parameters and loss information."))
    parser.add_argument("model_orientation_type",
                        help=("{iso, absolute, relative, full}\n- iso: model is isotropic, "
                              "predictions identical for all orientations.\n- absolute: model can"
                              " fit differences in absolute orientation, that is, in Cartesian "
                              "coordinates, such that sf_angle=0 correponds to 'to the right'\n- "
                              "relative: model can fit differences in relative orientation, that "
                              "is, in retinal polar coordinates, such that sf_angle=0 corresponds"
                              " to 'away from the fovea'\n- full: model can fit differences in "
                              "both absolute and relative orientations"))
    parser.add_argument("model_eccentricity_type",
                        help=("{scaling, constant, full}\n- scaling: model's relationship between"
                              " preferred period and eccentricity is exactly scaling, that is, the"
                              " preferred period is equal to the eccentricity.\n- constant: model'"
                              "s relationship between preferred period and eccentricity is exactly"
                              " constant, that is, it does not change with eccentricity but is "
                              "flat.\n- full: model discovers the relationship between "
                              "eccentricity and preferred period, though it is constrained to be"
                              " linear (i.e., model solves for a and b in period = a * "
                              "eccentricity + b)"))
    parser.add_argument("--model_vary_amplitude", '-v', action="store_true",
                        help=("Whether to allow the model to fit the parameters that control "
                              "amplitude as a function of orientation (whether this depends on "
                              "absolute orientation, relative orientation, or both depends on the"
                              " value of `model_orientation_type`)"))
    parser.add_argument("first_level_results_path",
                        help=("Path to the first level results dataframe containing the data to "
                              "fit."))
    parser.add_argument("save_path_stem",
                        help=("Path stem (no extension) where we'll save the results: model state "
                              " dict (`save_path_stem`_model.pt), loss dataframe "
                              "(`save_path_stem`_loss.csv), and first level dataframe with "
                              "performance  (`save_path_stem`_results_df.csv)"))
    parser.add_argument("--random_seed", default=None,
                        help=("we initialize the model with random parameters in order to try and"
                              " avoid local optima. we set the seed before generating all those "
                              "random numbers. If not specified, then we don't set it."))
    parser.add_argument("--train_thresh", '-t', default=1e-8, type=float,
                        help=("How little the loss can change with successive epochs to be "
                              "considered done training."))
    parser.add_argument("--df_filter", '-d', default='drop_voxels_with_negative_amplitudes',
                        help=("{'drop_voxels_near_border', 'drop_voxels_with_negative_amplitudes',"
                              " 'reduce_num_voxels:n', 'None'}."
                              " How to filter the first level dataframe. Can be multiple of these,"
                              " separated by a comma, in which case they will be chained in the "
                              "order provided (so the first one will be applied to the dataframe "
                              "first). If 'drop_voxels_near_border', will drop all voxels whose "
                              "pRF center is one sigma away from the stimulus borders. If "
                              "'drop_voxels_with_negative_amplitudes', drop any voxel that has a "
                              "negative response amplitude. If 'reduce_num_voxels:n', will drop "
                              "all but the first n voxels. If 'None', fit on all data (obviously,"
                              " this cannot be chained with any of the others)."))
    parser.add_argument("--batch_size", "-b", default=1, type=int,
                        help=("Size of the batches for training"))
    parser.add_argument("--max_epochs", '-e', default=100, type=int,
                        help=("Maximum number of training epochs (full runs through the data)"))
    parser.add_argument("--learning_rate", '-r', default=1e-2, type=float,
                        help=("Learning rate for Adam optimizer (should change inversely with "
                              "batch size)."))
    parser.add_argument("--stimulus_class", '-c', default=None, nargs='+',
                        help=("Which stimulus class(es) to consider part of the test set. should "
                              "probably only be one, but should work if you pass more than one as "
                              "well"))
    args = vars(parser.parse_args())
    # stimulus_class can be either None or some ints. argparse will hand us a list, so we have to
    # parse it appropriately
    stimulus_class = args.pop('stimulus_class')
    try:
        stimulus_class = [int(i) for i in stimulus_class]
    except ValueError:
        # in this case, we can't cast one of the strs in the list to an int, so we assume it must
        # just contain None.
        stimulus_class = None
    df_filter = construct_df_filter(args.pop('df_filter'))
    main(stimulus_class=stimulus_class, df_filter=df_filter, **args)
