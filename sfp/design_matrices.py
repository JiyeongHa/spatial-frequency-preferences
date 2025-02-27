#!/usr/bin/python
"""functions to create the design matrices used in our first-level MRI analysis.
"""
import matplotlib as mpl
import re
# we do this because sometimes we run this without an X-server, and this backend doesn't need
# one. We set warn=False because the notebook uses a different backend and will spout out a big
# warning to that effect; that's unnecessarily alarming, so we hide it.
import numpy as np
import argparse
import warnings
import nibabel as nib
import pandas as pd
import os
import json
import matplotlib.pyplot as plt
from bids import BIDSLayout
from collections import Counter


def _discover_class_size(values):
    class_size = 0
    break_out = False
    while not break_out:
        class_size += 1
        tmp = np.abs(values[:-class_size:class_size] - values[class_size::class_size])
        class_changes = np.nonzero(tmp)[0]
        indices = np.array(range(len(tmp)))
        if len(class_changes) == len(indices):
            break_out = np.equal(class_changes, indices).all()
    return class_size


def _find_stim_class_length(value, class_size, blanks_have_been_dropped=True):
    """helper function to find the length of one stimulus class / trial type, in seconds
    """
    lengths = (value[1:] - value[:-1]).astype(float)
    counts = Counter(np.round(lengths, 1))
    real_length = counts.most_common()[0][0]
    counts.pop(real_length)
    if blanks_have_been_dropped:
        counts.pop(real_length + class_size * real_length)
    for i in counts.keys():
        if (np.abs(i - real_length)/real_length > .005):
            perc_diff = (np.abs(lengths - real_length) / real_length) * 100
            warnings.warn("One of your stimuli lengths is greater than .5 percent different than the "
                          "assumed length of %s! It differs by %.02f percent" %
                          (real_length, perc_diff))
    return real_length * class_size


def create_design_matrix(tsv_df, n_TRs):
    """create and return the design matrix for a run

    tsv_df: pandas DataFrame describing the design of the experiment and the stimulus classes
    (created by loading run's events.tsv file)
    """
    # because the values are 0-indexed
    design_matrix = np.zeros((n_TRs, tsv_df.trial_type.max()+1))
    for i, row in tsv_df.iterrows():
        row = row[['Onset time (TR)', 'trial_type']].astype(int)
        design_matrix[row['Onset time (TR)'], row['trial_type']] = 1
    return design_matrix


def check_design_matrix(design_matrix, run_num=None, model_blanks=False):
    """quick soundness test to double-check design matrices

    this just checks to make sure that each event happens exactly once and that each TR has 0 or 1
    events.
    """
    if not model_blanks:
        if not (design_matrix.sum(0) == 1).all():
            raise Exception("There's a problem with the design matrix%s, at least one event doesn't"
                            " show up once!" % {None: ''}.get(run_num, " for run %s" % run_num))
    else:
        if not (design_matrix.sum(0)[:-1] == 1).all():
            raise Exception("There's a problem with the design matrix%s, at least one non-blank "
                            "event doesn't show up once!" % {None: ''}.get(run_num, " for run %s" % run_num))
        if design_matrix.sum(0)[-1] != model_blanks:
            raise Exception("There's a problem with the design matrix%s, the blank event doesn't "
                            "show up the correct number of times!" % {None: ''}.get(run_num, " for run %s" % run_num))
    if not ((design_matrix.sum(1) == 0) + (design_matrix.sum(1) == 1)).all():
        raise Exception("There's a problem with the design matrix%s, at least one TR doesn't have"
                        " 0 or 1 events!" % {None: ''}.get(run_num, " for run %s" % run_num))


def plot_design_matrix(design_matrix, title, save_path=None):
    """plot design matrix and, if save_path is set, save the resulting image
    """
    fig = plt.figure(figsize=(10, 10))
    ax = fig.add_subplot(111, aspect='equal')
    ax.imshow(design_matrix, 'gray')
    ax.axes.grid(False)
    plt.xlabel("Stimulus class")
    plt.ylabel("TR")
    plt.title(title)
    if save_path is not None:
        ax.figure.savefig(save_path, bbox_inches='tight')


def create_all_design_matrices(BIDS_directory, subject, session, mat_type="stim_class",
                               permuted=False,
                               save_path="data/MRI_first_level/run-%02d_design.tsv"):
    """create and save design matrices for all runs in a specified scanning session

    BIDS_directory should be a path to (base) a BIDS directory. subject and session specify which
    scanning session we're handling, and we will then construct a design matrix for each events.tsv
    file found there. all runs must have the same TR for GLMdenoise, so we'll through an exception
    if that's not the case.

    save_path should contain some string formatting symbol (e.g., %s, %02d) that can indicate the
    run number and should end in .tsv

    mat_type: {"stim_class", "all_visual", "stim_class_N_blanks"}. What design matrix to
    make. stim_class has each stimulus class as a separate regressor and is our actual design
    matrix for the experiment. all_visual has every stimulus class combined into regressor (so that
    that regressors represents whenever anything is on the screen) and is used to check that things
    are working as expected, since every voxel in the visual cortex should then show increased
    activation relative to baseline. stim_class_N_blanks (where N is an integer in format %02d
    between 1 and 10, inclusive) is the same as stimulus class, except we also model N of the
    blanks in a separate class. This class will have the highest trial type / model class number
    (so if there are 52 classes without blanks, the blanks will be in class 53).

    permuted: boolean, default False. Whether to permute the run labels or not. The reason to do
    this is to double-check your results: your R2 values should be much lower when permuted,
    because you're basically breaking your hypothesized connection between the GLM model and brain
    activity.

    """
    # want these without the leading tags
    subject = subject.replace('sub-', '')
    session = session.replace('ses-', '')
    if mat_type in ['stim_class', 'all_visual']:
        model_blanks = False
    elif 'stim_class' in mat_type and '_blanks' in mat_type:
        model_blanks = int(mat_type.replace('stim_class_', '').replace('_blanks', ''))
        if model_blanks == 0 or model_blanks > 10:
            raise Exception("for mat_type stim_class_N_blanks, N must lie between 1 and 10, inclusive!")
    else:
        raise Exception("Don't know how to handle mat_type %s!" % mat_type)
    # having an issue: https://github.com/bids-standard/pybids/issues/339
    layout = BIDSLayout(BIDS_directory, validate=False)
    run_nums = layout.get_runs(subject=subject, session=session)
    stim_lengths = []
    TR_lengths = []
    if not os.path.exists(os.path.dirname(save_path)):
        os.makedirs(os.path.dirname(save_path))
    name_stub = re.findall(r'run.*_design\.tsv', save_path)
    if len(name_stub) != 1:
        raise Exception("Unsure how to convert design matrix save_path to run detail save path!")
    run_details_save_path = save_path.replace(name_stub[0], 'params.json')
    save_labels = np.array(run_nums).copy()
    if permuted is True:
        if 'permuted' not in save_path:
            save_path = save_path.replace('.tsv', '_permuted.tsv')
        # this shuffles in place, ensuring that every value is moved:
        while len(np.where(save_labels == run_nums)[0]) != 0:
            np.random.shuffle(save_labels)
        if 'permuted' not in run_details_save_path:
            run_details_save_path = run_details_save_path.replace('.json', '_permuted.json')
    for run_num, save_num in zip(run_nums, save_labels):
        tsv_file = layout.get(suffix='events', run=run_num, subject=subject, session=session,
                              extensions='tsv')
        if len(tsv_file) != 1:
            raise IOError("Need one tsv for run %s, but found %d!" % (run_num, len(tsv_file)))
        # by default, pandas interprets empty fields as NaNs. We have some empty strings in the
        # "notes" column, which we want to interpret as empty strings
        tsv_df = pd.read_csv(tsv_file[0].path, sep='\t', na_filter=False)
        # rows with trial_type == n/a are digit-only trials, the blank trials
        # preceding and following the scan. we ignore them.
        tsv_df = tsv_df[tsv_df.trial_type != 'n/a']
        # cast these columns back to numeric, now that we've removed the rows
        # that had n/a in them.
        tsv_df = tsv_df.astype({'stim_file_index': int, 'trial_type': int})
        class_size = _discover_class_size(tsv_df.trial_type.values)
        # We let _find_stim_class_length know that no blanks have been dropped, so even the blank
        # trials are included (and thus the time between all onsets in the tsv should be the same)
        stim_lengths.append(_find_stim_class_length(tsv_df.onset.values, class_size, False))
        tsv_df = tsv_df[::class_size]
        # the note field is either empty or contains the string "blank trial", so we definitely
        # want to grab the indices of the non-blank trials, as they're always included
        idx = tsv_df[tsv_df.note == "n/a"].index
        if model_blanks:
            # this grabs a sub-sample of the blank trials
            blank_idx = tsv_df[tsv_df.note == 'blank trial'].sample(model_blanks).index
            # and adds it to the index we're using, making sure it's in the right order
            idx = idx.append(blank_idx).sort_values()
        tsv_df = tsv_df.loc[idx]
        nii_file = layout.get(suffix='bold', run=run_num, subject=subject, session=session,
                              extensions=['nii', 'nii.gz'])
        if len(nii_file) != 1:
            raise IOError("Need one nifti for run %s, but found %d!" % (run_num, len(nii_file)))
        nii = nib.load(nii_file[0].path)
        n_TRs = nii.shape[3]
        TR = nii_file[0].metadata['RepetitionTime']
        stim_times = tsv_df.onset.values
        stim_times = np.repeat(np.expand_dims(stim_times, 1), n_TRs, 1)
        TR_times = [TR * i for i in range(n_TRs)]
        time_from_TR = np.round(stim_times - TR_times)
        tsv_df['Onset time (TR)'] = np.where(time_from_TR == 0)[1]
        design_mat = create_design_matrix(tsv_df, n_TRs)
        TR_lengths.append(TR)
        check_design_matrix(design_mat, run_num, model_blanks)
        if mat_type == "all_visual":
            design_mat = design_mat.sum(1).reshape((design_mat.shape[0], 1))
        plot_design_matrix(design_mat, "Design matrix for run %s" % save_num,
                           save_path.replace('.tsv', '.svg') % save_num)
        np.savetxt(save_path % save_num, design_mat, '%d', '\t')
    assert ((np.array(stim_lengths) - stim_lengths[0]) == 0).all(), "You have different stim lengths!"
    assert ((np.array(TR_lengths) - TR_lengths[0]) == 0).all(), "You have different TR lengths!"
    with open(run_details_save_path, 'w') as f:
        run_details = {"stim_length": stim_lengths[0], 'TR_length': TR_lengths[0],
                       # this needs to be converted to regular python ints, not numpy's int64,
                       # which is not JSON-serializable
                       'save_labels': [int(i) for i in save_labels], 'run_numbers': list(run_nums)}
        json.dump(run_details, f)


if __name__ == '__main__':
    class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass
    parser = argparse.ArgumentParser(
        description=("Create and save design matrices for each events.tsv file found for a given"
                     " subject, session (that is, all runs for a given scanning session). All runs"
                     " must have the same TR for GLMdenoise, so we'llthrow an exception if that's"
                     " not the case. We'll also throw an exception if we find more than one events"
                     " file or nifti for a given subject, session, run."),
        formatter_class=CustomFormatter)
    parser.add_argument("BIDS_directory",
                        help=("Path to the (base) BIDS directory for this project."))
    parser.add_argument("subject",
                        help=("The BIDS subject to make the design matrices for"))
    parser.add_argument("session",
                        help=("The BIDS session to make the design matrices for"))
    parser.add_argument("--save_path",
                        default="data/MRI_first_level/run-%02d_design.tsv",
                        help=("Template path that we should save the resulting design matrices in."
                              "Must contain at least one string formatting signal (to indicate run"
                              "number) and must end in .tsv."))
    parser.add_argument("--mat_type", default="stim_class",
                        help=("{'stim_class', 'all_visual', 'stim_class_N_blanks'}. What design "
                              "matrix to make. stim_class has each stimulus class as a separate "
                              "regressor and is our actual design matrix for the experiment. "
                              "all_visual has every stimulus class combined into regressor (so that" 
                              "that regressors represents whenever anything is on the screen) and "
                              "is used to check that things are working as expected, since every "
                              "voxel in the visual cortex should then show increased activation "
                              "relative to baseline. stim_class_N_blanks (where N is a zero-padded"
                              " integer between 1 and 10, inclusive) is the same as stimulus "
                              "class, except we also model N of the blanks in a separate class. "
                              "This class will have the highest trial type / model class number ("
                              "so if there are 52 classes without blanks, the blanks will be in "
                              "class 53)."))
    parser.add_argument("--permuted", '-p', action="store_true",
                        help=("Whether to permute the run labels or not. The reason to do this is"
                              " to double-check your results: your R2 values should be much lower "
                              "when permuted, because you're basically breaking your hypothesized"
                              " connection between the GLM model and brain activity."))
    args = vars(parser.parse_args())
    create_all_design_matrices(**args)
