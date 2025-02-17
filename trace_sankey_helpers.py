"""Helper functions for showing traces as Sankey diagrams."""

import time
import numpy as np
import pandas as pd
import ipywidgets
from floweaver import Dataset, weave
from palettable.colorbrewer import qualitative, sequential


def inputs_flows_as_dataframe(processes, possible_inputs, I, F):
    """Turn inputs & flows vectors into dataframe of flows"""
    flows = []
    Np = F.shape[0]
    for i in range(len(I)):
        if I[i] > 0:
            flows.append(('inputs', possible_inputs[i], '?', I[i]))

    # lookup process id to index
    process_ids = list(processes.keys())
    for i in range(Np):
        for j in range(Np):
            if F[i, j] > 0:
                flows.append((process_ids[i], process_ids[j], '?', F[i, j]))
    return pd.DataFrame.from_records(flows, columns=('source', 'target', 'material', 'value'))


def flows_from_trace(processes, possible_inputs, trace, nburn=100, thin=10):
    inputs = trace['inputs', nburn::thin]
    flows = trace['F', nburn::thin]

    # lookup process id to index
    process_ids = list(processes.keys())

    Np = flows.shape[1]
    rows = []
    for i in range(flows.shape[0]):
        for j in range(inputs.shape[1]):
            if inputs[i, j] > 0:
                rows.append(('inputs', possible_inputs[j], '?', i, inputs[i, j]))

        for j in range(Np):
            for k in range(Np):
                if flows[i, j, k] > 0:
                    rows.append((process_ids[j], process_ids[k], '?', i, flows[i, j, k]))

    return pd.DataFrame.from_records(rows, columns=('source', 'target', 'material', 'sample', 'value'))


def show_sample(processes, possible_inputs, trace, isamp, sdd, widget=None, burn=500):
    if isamp is None:
        I = trace['inputs', burn:].mean(axis=0)
        F = trace['F', burn:].mean(axis=0)
        dataset = Dataset(inputs_flows_as_dataframe(processes, possible_inputs, I, F))
    else:
        I = trace['inputs'][isamp]
        F = trace['F'][isamp]
        dataset = Dataset(inputs_flows_as_dataframe(processes, possible_inputs, I, F))
    new_widget = weave(sdd, dataset).to_widget(width=600, height=300,
                                               margins=dict(left=50, right=100, top=10, bottom=10))
    if widget is None:
        return new_widget
    else:
        widget.value = new_widget.value


def animate_samples(processes, possible_inputs, trace, sdd, rescale=False):
    def dataset(isamp):
        I = trace['inputs'][isamp]
        F = trace['F'][isamp]
        return Dataset(inputs_flows_as_dataframe(processes, possible_inputs, I, F))

    widget = weave(sdd, dataset(0)).to_widget(width=800, height=500,
                                              margins=dict(left=50, right=100, top=10, bottom=10))
    button = ipywidgets.Button(description='Go')
    box = ipywidgets.VBox([button, widget])

    def update(isamp):
        new_widget = weave(sdd, dataset(isamp)).to_widget(width=600, height=300,
                                                          margins=dict(left=50, right=100, top=10, bottom=10))
        widget.links = new_widget.links

    def play(_):
        try:
            for i in range(0, len(trace), 10):
                update(i)
                if rescale:
                    widget.set_scale()
                time.sleep(0.5)
        except KeyboardInterrupt:
            return

    button.on_click(play)

    return box


import floweaver
import ipywidgets
from ipysankeywidget import SankeyWidget
import matplotlib as mpl
import matplotlib.pyplot as plt
import pymc3 as pm

def hpd_range(x):
    hpd = pm.hpd(x)
    return hpd[1] - hpd[0]

# From matplotlib.colours
def rgb2hex(rgb):
    'Given an rgb or rgba sequence of 0-1 floats, return the hex string'
    return '#%02x%02x%02x' % tuple([int(np.round(val * 255)) for val in rgb[:3]])


def weave_variance(flows, sdd, normed=False, vlim=None, palette=None):
    if palette is None:
        palette = sequential.Reds_9.mpl_colormap

    # Aggregate
    def measures(group):
        agg = group.groupby('sample').agg({'value': 'sum'})
        return {'value': agg['value'].values}

    def link_width(data):
        return data['value'].mean()

    scale = (NormalisedHPDRangeScale('value', palette=palette) if normed else
             AbsoluteHPDRangeScale('value', palette=palette))

    if vlim is not None:
        scale.set_domain(vlim)

    result = weave(sdd, flows, measures=measures, link_width=link_width, link_color=scale)

    return result, scale.get_domain()


def show_variance(flows, sdd, normed=False, vlim=None, width=800, palette=None):
    result, vlim = weave_variance(flows, sdd, normed, vlim, palette)

    colorbar(palette, scale.domain[0], scale.domain[1],
             'Credible interval width' + (' (normalised)' if normed else ' [Mt]'))

    return result.to_widget(width=width, height=400,
                            margins=dict(top=15, bottom=10, left=100, right=100))


def save_variance(flows, sdd, normed=False, vlim=None, palette=None):
    result, vlim = weave_variance(flows, sdd, normed, vlim, palette)
    return result.to_json()


def _calc_variance(flows, sdd, normed, vlim, palette):
    dataset = floweaver.Dataset(flows)
    G, groups = floweaver.sankey_view(sdd, dataset)

    if normed:
        hue = lambda data: hpd_range(data['value']) / data['value'].mean()
    else:
        hue = lambda data: hpd_range(data['value'])

    values = np.array([hue(data) for _, _, data in G.edges(data=True)])
    if vlim is None:
        vmin, vmax = values.min(), values.max()
        print('Range: {:.3g} to {:.3g}'.format(vmin, vmax))
    else:
        vmin, vmax = vlim

    get_color = lambda m, data: rgb2hex(palette((hue(data) - vmin) / (vmax - vmin)))

    value = floweaver.graph_to_sankey(G, groups, sample='mean', flow_color=get_color)
    return value, vmin, vmax


class AbsoluteHPDRangeScale(floweaver.QuantitativeScale):
    def get_value(self, link, measures):
        return hpd_range(measures['value'])


class NormalisedHPDRangeScale(floweaver.QuantitativeScale):
    def get_value(self, link, measures):
        return hpd_range(measures['value']) / measures['value'].mean()


def colorbar(cmap, vmin, vmax, label):
    # Make a figure and axes with dimensions as desired.
    fig = plt.figure(figsize=(1.21, 0.2))
    ax1 = fig.add_axes([0.05, 0.25, 0.9, 0.9])

    # Set the colormap and norm to correspond to the data for which
    # the colorbar will be used.
    norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
    cb = mpl.colorbar.ColorbarBase(ax1, cmap=cmap,
                                   norm=norm,
                                   orientation='horizontal')
    cb.set_label(label)
    cb.set_ticks([vmin, vmax])

    return fig
