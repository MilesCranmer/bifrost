# Copyright (c) 2016, The Bifrost Authors. All rights reserved.
# Copyright (c) 2016, NVIDIA CORPORATION. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
# * Neither the name of The Bifrost Authors nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""@module ionospheric_pipeline
This program serves as an example of Bifrost's usage in an ionospheric sensing pipeline
"""
import operator
import numpy as np
import ephem
from bifrost.block import (
        NumpyBlock, TestingBlock, GainSolveBlock, NearestNeighborGriddingBlock,
        IFFT2Block, Pipeline)
from bifrost.addon.leda.blocks import (
    ScalarSkyModelBlock, DELAYS, COORDINATES, DISPERSIONS, UVCoordinateBlock,
    load_telescope, LEDA_SETTINGS_FILE, OVRO_EPHEM, NewDadaReadBlock, CableDelayBlock,
    BAD_STANDS, ImagingBlock, SPEED_OF_LIGHT)
import hickle as hkl

PIXEL_DIAMETER_PER_MHZ = 4.8677

def load_sources():
    sources = {}
    with open('/data1/mcranmer/data/real/vlssr_catalog.txt', 'r') as file_in:
        iterator = 0
        for line in file_in:
            iterator += 1
            if iterator == 17:
                break
        iterator = 0
        number_sources = 100000
        total_flux = 1e-10
        used = 0
        for line in file_in:
            iterator += 1
            if iterator > number_sources:
                #break
                pass
            if line[0].isspace():
                continue
            try:
                flux = float(line[29:36].replace(" ",""))
            except:
                break
            if flux > 1:
                source_string = line[:-1]
                ra = line[:2]+':'+line[3:5]+':'+line[6:11]
                ra = ra.replace(" ", "")
                dec = line[12:15]+':'+line[16:18]+':'+line[19:23]
                dec = dec.replace(" ", "")
                total_flux += flux
                sources[str(used)] = {
                    'ra': ra, 'dec': dec,
                    'flux': flux, 'frequency': 74e6, 
                    'spectral index': -0.7}
                used += 1
    return sources

def slice_away_uv(model_and_uv):
    """Cut off the uv coordinates from the ScalarSkyModelBlock and reshape to GainSolve"""
    number_stands = model_and_uv.shape[1]
    model = np.zeros(shape=[1, number_stands, 2, number_stands, 2]).astype(np.complex64)
    uv_coords = np.zeros(shape=[number_stands, number_stands, 2]).astype(np.float32)
    model[0, :, 0, :, 0] = model_and_uv[0, :, :, 2]+1j*model_and_uv[0, :, :, 3]
    model[0, :, 1, :, 1] = model[0, :, 0, :, 0]
    uv_coords[:, :, 0:2] = model_and_uv[0, :, :, 0:2]
    return model, uv_coords

def reformat_data_for_gridding(visibilities, uv_coordinates):
    """Reshape visibility data for gridding on UV plane"""
    reformatted_data = np.zeros(shape=[256, 256, 4], dtype=np.float32)
    reformatted_data[:, :, 0] = uv_coordinates[:, :, 0]
    reformatted_data[:, :, 1] = uv_coordinates[:, :, 1]
    reformatted_data[:, :, 2] = np.real(visibilities[0, :, 0, :, 0])
    reformatted_data[:, :, 3] = np.imag(visibilities[0, :, 0, :, 0])
    return reformatted_data

def transpose_to_gain_solve(data_array):
    """Transpose the DADA data to the gain_solve format"""
    return data_array.transpose((0, 1, 3, 2, 4))

sources = {}
sources['cyg'] = {
    'ra':'19:59:28.4', 'dec':'+40:44:02.1', 'flux': 10571.0, 'frequency': 58e6,
    'spectral index': -0.2046}
sources['cas'] = {
    'ra': '23:23:27.8', 'dec': '+58:48:34',
    'flux': 6052.0, 'frequency': 58e6, 'spectral index':(+0.7581)}
del sources['cas']
blocks = []
dada_file = '/data2/hg/interfits/lconverter/WholeSkyL64_47.004_d20150203_utc181702_test/2015-04-08-20_15_03_0001133593833216.dada'
#dada_file = '/data1/mcranmer/data/real/leda/2015-04-08-20_15_03_0001133593833216.dada'

OVRO_EPHEM.date = '2015/04/09 14:34:51'
cfreq = 47.004e6
#cfreq = 36.54e6
bandwidth = 2.616e6
df = bandwidth/109.0
output_channels = np.array([84])
nstand = 256
nchan = 1
npol = 2
frequencies = cfreq - bandwidth/2 + df*output_channels
stand_flags = 2*np.ones(shape=[1, nstand]).astype(np.int8)
for stand in BAD_STANDS:
    stand_flags[0, stand] = 1

########################################
#Dummy jones
jones = np.ones([nchan, npol, nstand, npol]).astype(np.complex64)
jones[:, 0, :, 1] = 0
jones[:, 1, :, 0] = 0
blocks.append((TestingBlock(jones), [], ['jones_in']))
########################################

########################################
#Load in data and apply cable delays
blocks.append((
    NewDadaReadBlock(dada_file, output_chans=output_channels, time_steps=1),
    {'out': 'raw_visibilities'}))
blocks.append((
    CableDelayBlock(frequencies, DELAYS, DISPERSIONS),
    {'in':'raw_visibilities', 'out':'visibilities'}))
blocks.append((
    NumpyBlock(transpose_to_gain_solve),
    {'in_1': 'visibilities', 'out_1': 'formatted_visibilities'}))
########################################

def nonzero_median(array):
    return np.median(array[np.nonzero(array)])
########################################
#Zero bad stands in data
def flag_bad_stands(data_visiblities):
    """Flag all of the bad stands"""
    visibilities = np.copy(data_visiblities)
    if np.max(np.abs(visibilities)) == 0:
        return visibilities
    visibilities[:, BAD_STANDS, :, :, :] = 0
    visibilities[:, :, :, BAD_STANDS, :] = 0
    return visibilities
########################################

########################################
#Flagging functions
def baseline_threshold_against_self(data):
    """Flag visibilities if above median of self"""
    if np.max(np.abs(data)) == 0: 
        return data
    median_data = nonzero_median(np.abs(data[:, :, 0, :, 0]))
    flags = np.abs(data[:, :, 0, :, 0]/median_data) > 10
    print np.sum(flags), "baselines thresholded by amplitude"
    flagged_data = np.copy(data)
    for x, y in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        flagged_data[:, :, x, :, y][flags] = 0
    return flagged_data

def baseline_threshold_against_model(model, data):
    """Flag a visibility against calibration if it is above a threshold value"""
    if np.max(np.abs(model)) == 0: 
        return model, data
    normed_data = data/nonzero_median(np.abs(data[:, :, 0, :, 0]))
    normed_model = model/nonzero_median(np.abs(model[:, :, 0, :, 0]))
    upper_threshold = 10
    lower_threshold = 0.0001
    flags1 = np.abs(normed_data[:, :, 0, :, 0]) > upper_threshold*np.abs(normed_model[:, :, 0, :, 0])
    flags2 = np.abs(normed_data[:, :, 0, :, 0]) < lower_threshold*np.abs(normed_model[:, :, 0, :, 0])
    flags3 = np.abs(normed_data[:, :, 1, :, 1]) > upper_threshold*np.abs(normed_model[:, :, 1, :, 1])
    flags4 = np.abs(normed_data[:, :, 1, :, 1]) < lower_threshold*np.abs(normed_model[:, :, 1, :, 1])
    flags = np.logical_or(np.logical_or(flags1, flags2), np.logical_or(flags3, flags4))
    print np.sum(flags), "baselines thresholded against model"
    flagged_model = np.copy(model)
    flagged_data = np.copy(data)
    for x, y in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        flagged_model[:, :, x, :, y][flags] = 0
        flagged_data[:, :, x, :, y][flags] = 0
    return flagged_model, flagged_data

def baseline_length_flagger(model, data):
    """Flag visibilities if the corresponding baseline is too short"""
    if np.max(np.abs(model)) == 0:
        return model, data
    baselines = np.sqrt(np.square(COORDINATES[:, None] - COORDINATES[None, :]).sum(axis=2))
    wavelengths = SPEED_OF_LIGHT/np.array(frequencies[0])
    flags = baselines < 10*wavelengths
    flagged_data = np.copy(data)
    flagged_model = np.copy(model)
    print np.sum(flags), "baselines thresholded by length"
    for x, y in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        flagged_model[0, :, x, :, y][flags] = 0
        flagged_data[0, :, x, :, y][flags] = 0
    return flagged_model, flagged_data
########################################

########################################
#Use of gain solution functions
def apply_gains(data, jones):
    """Apply the solutions to uncalibrated data"""
    calibrated_data = np.copy(data)
    for i in range(256):
        for j in range(256):
            if i in BAD_STANDS or j in BAD_STANDS:
                calibrated_data[0, i, :, j, :] = 0
            else:
                calibrated_data[0, i, :, j, :] = np.dot(np.conj(np.transpose(jones[0, :, i, :])), np.dot(calibrated_data[0, i, :, j, :], jones[0, :, j, :]))
    return calibrated_data

def apply_inverse_gains(data, jones):
    """Apply the inverse solutions to model data"""
    calibrated_data = np.copy(data)
    invjones = np.copy(jones)
    if np.max(np.abs(data)) == 0:
        return data
    for i in range(256):
        try:
            invjones[0, :, i, :] = np.linalg.inv(jones[0, :, i, :])
        except np.linalg.LinAlgError:
            invjones[0, :, i, :] = 0
    for i in range(256):
        for j in range(256):
            if i in BAD_STANDS or j in BAD_STANDS:
                calibrated_data[0, i, :, j, :] = 0
            else:
                calibrated_data[0, i, :, j, :] = np.dot(np.conj(np.transpose(invjones[0, :, i, :])), np.dot(calibrated_data[0, i, :, j, :], invjones[0, :, j, :]))
    return calibrated_data
########################################

########################################
#Source configuration routines
def subtract_source(visibilities, source):
    """Remove the source from the data set"""
    if np.max(np.abs(visibilities)) == 0:
        return visibilities
    return visibilities-source

def subtract_sources(visibilities, *sources):
    """Remove multiple sources from the data set"""
    clean_visibilities = np.copy(visibilities)
    for source in sources:
        clean_visibilities -= source
    return clean_visibilities

def below_horizon(source):
    """Say if the source is below the horizon for LEDA"""
    source_position = ephem.FixedBody()
    source_position_ra = source['ra']
    source_position_dec = source['dec']
    source_position._ra = source_position_ra
    source_position._dec = source_position_dec
    source_position.compute(OVRO_EPHEM)
    altitude = np.float(repr(source_position.alt))
    return (altitude < 0)
########################################

########################################
#Initial flagging against RFI and bad stands
blocks.append([
    NumpyBlock(baseline_threshold_against_self),
    {'in_1':'formatted_visibilities', 'out_1':'almost_clean_formatted_visibilities'}])
blocks.append([
    NumpyBlock(flag_bad_stands),
    {'in_1':'almost_clean_formatted_visibilities', 'out_1':'clean_formatted_visibilities'}])
########################################

########################################
#Normalize the visibilities into the first iteration
def normalize_median(array):
    if np.max(np.abs(array))== 0:
        return array
    return array/nonzero_median(np.abs(array[:, :, 0, :, 0]))
blocks.append([
    NumpyBlock(normalize_median),
    {'in_1':'clean_formatted_visibilities', 'out_1': 'iterate_visibilities0'}])
########################################

########################################
#PREPEEL: Perform an initial calibration to every source, and subtract off.
allsources = load_sources()
fluxes_list = {str(i):allsources[str(i)]['flux'] for i in range(len(allsources))}
all_sorted_fluxes = sorted(fluxes_list.items(), key=operator.itemgetter(1))[-1::-1]
#Delete overlapping sources:
overlapping_sources = [2, 3, 4, 5, 6, 9, 12, 15, 16]
sorted_fluxes = []
for i in range(200):
    if i not in overlapping_sources:
        sorted_fluxes.append(all_sorted_fluxes[i])
current_ring = 0
i = 0
#Image Cyg and Cas at the same time!
del sorted_fluxes[0]
total_sources = 4
while current_ring < total_sources:
    current_source = {str(i):{}}
    current_source[str(i)]['flux'] = allsources[sorted_fluxes[i][0]]['flux']
    current_source[str(i)]['ra'] = allsources[sorted_fluxes[i][0]]['ra']
    current_source[str(i)]['dec'] = allsources[sorted_fluxes[i][0]]['dec']
    current_source[str(i)]['spectral index'] = allsources[sorted_fluxes[i][0]]['spectral index']
    current_source[str(i)]['frequency'] = allsources[sorted_fluxes[i][0]]['frequency']
    ####################################
    #Generate the source model
    if below_horizon(allsources[sorted_fluxes[i][0]]):
        i+=1
        continue
    if i == 0:
        # (Cas selected, so do a two source model)
        sources = {}
        sources['cyg'] = {
            'ra':'19:59:28.4', 'dec':'+40:44:02.1', 'flux': 10571.0, 'frequency': 58e6,
            'spectral index': -0.2046}
        sources['cas']= {
            'ra': '23:23:27.8', 'dec': '+58:48:34',
            'flux': 6052.0, 'frequency': 58e6, 'spectral index':(+0.7581)}
        blocks.append((
            ScalarSkyModelBlock(OVRO_EPHEM, COORDINATES, frequencies, sources),
            [], ['model+uv'+str(current_ring)]))
    else:
        blocks.append((
            ScalarSkyModelBlock(OVRO_EPHEM, COORDINATES, frequencies, {str(i): allsources[sorted_fluxes[i][0]]}),
            [], ['model+uv'+str(current_ring)]))
    if current_ring == 0: 
        coordinate_output = 'uv_coords'
    else:
        coordinate_output = 'trash'+str(10.5*current_ring+1.2423)
    blocks.append((
        NumpyBlock(slice_away_uv, outputs=2),
        {'in_1': 'model+uv'+str(current_ring), 'out_1': 'initial_model'+str(current_ring),
         'out_2': coordinate_output}))
    blocks.append((
        NumpyBlock(flag_bad_stands),
        {'in_1': 'initial_model'+str(current_ring), 'out_1': 'model'+str(current_ring)}))
    ####################################

    ####################################
    #Flag the model and visibilities
    blocks.append([
        NumpyBlock(baseline_threshold_against_model, inputs=2, outputs=2),
        {'in_1':'model'+str(current_ring), 'in_2': 'iterate_visibilities'+str(current_ring),
        'out_1': 'thresholded_model'+str(current_ring), 'out_2': 'thresholded_visibilities'+str(current_ring)}])
    blocks.append([
        NumpyBlock(baseline_length_flagger, inputs=2, outputs=2),
        {'in_1': 'thresholded_model'+str(current_ring), 'in_2': 'thresholded_visibilities'+str(current_ring),
        'out_1': 'long_model'+str(current_ring), 'out_2': 'long_visibilities'+str(current_ring)}])
    ####################################

    ####################################
    #Solve for gains and renormalize
    blocks.append([NumpyBlock(np.copy), {'in_1': 'jones_in', 'out_1': 'jones_in'+str(current_ring)}])
    blocks.append([
        GainSolveBlock(flags=stand_flags, eps=0.5, max_iterations=10, l2reg=0.0),
        {'in_data': 'long_visibilities'+str(current_ring), 'in_model': 'long_model'+str(current_ring),
         'in_jones': 'jones_in'+str(current_ring), 'out_data': 'trash'+str(10.5*current_ring+1),
         'out_jones': 'jones_out'+str(current_ring)}])
    ####################################

    ####################################
    #Apply the gains to the model
    blocks.append([
        NumpyBlock(apply_inverse_gains, inputs=2),
        {'in_1': 'thresholded_model'+str(current_ring), 'in_2': 'jones_out'+str(current_ring),
         'out_1': 'adjusted_model'+str(current_ring)}])
    ####################################

    ####################################
    #Scale source to brightest point.
    for view_base in ['adjusted_model', 'thresholded_visibilities']:
        view = view_base + str(current_ring) + 'working'
        blocks.append((
            NumpyBlock(reformat_data_for_gridding, inputs=2),
            {'in_1': view_base+str(current_ring), 'in_2': 'uv_coords', 'out_1': view+'_data_for_gridding'}))
        blocks.append((
            NearestNeighborGriddingBlock((256, 256)),
            [view+'_data_for_gridding'], [view+'_grid']))
        blocks.append((IFFT2Block(), [view+'_grid'], [view+'_image']))

    def scale_ninety_ninth(reference_dst, reference_src, array):
        """Scale the 99th percentile pixel to equality"""
        if np.max(np.abs(reference_dst)) == 0:
            return array
        reference_pixel = np.percentile(np.abs(reference_dst), 99)
        amplitude_fraction = reference_pixel/np.percentile(np.abs(reference_src), 99)
        return array*amplitude_fraction

    blocks.append([
        NumpyBlock(scale_ninety_ninth, inputs=3),
        {'in_1': 'thresholded_visibilities'+str(current_ring)+'working_image',
        'in_2': 'adjusted_model'+str(current_ring)+'working_image',
        'in_3': 'adjusted_model'+str(current_ring),
        'out_1': 'scaled_model'+str(current_ring)}])
    ####################################

    ####################################
    #Subtract 'uncalibrated' source model from visibilities
    blocks.append([
        NumpyBlock(subtract_source, inputs=2),
        {'in_1': 'iterate_visibilities'+str(current_ring),
        'in_2': 'scaled_model'+str(current_ring),
        'out_1': 'iterate_visibilities'+str(current_ring+1)}])
    ####################################
    i+=1
    current_ring += 1

blocks.append([NumpyBlock(np.copy), {'in_1': 'iterate_visibilities'+str(current_ring), 'out_1': 'peeled_sky'}])

########################################
#PEEL: Put back sources one at a time and calibrate new solutions
current_ring = 0
while current_ring < total_sources - 1:
    ####################################
    #Add the source back in
    def add_source(background, source):
        print "background, source flux:"
        print np.max(np.abs(background))
        print np.max(np.abs(source))
        return background + source
    #TODO: Use flags from above here.
    blocks.append([NumpyBlock(add_source, inputs=2),
        {'in_1': 'peeled_sky', 'in_2': 'scaled_model'+str(current_ring),
        'out_1': 'unpeeled_sky'+str(current_ring)}])
    ####################################

    ####################################
    #Flag the model and visibilities
    blocks.append([
        NumpyBlock(baseline_threshold_against_model, inputs=2, outputs=2),
        {'in_1':'model'+str(current_ring), 'in_2': 'unpeeled_sky'+str(current_ring),
        'out_1': 'peeler_thres_model'+str(current_ring), 'out_2': 'unpeeled_thres_sky'+str(current_ring)}])
    blocks.append([
        NumpyBlock(baseline_length_flagger, inputs=2, outputs=2),
        {'in_1': 'peeler_thres_model'+str(current_ring), 'in_2': 'unpeeled_thres_sky'+str(current_ring),
        'out_1': 'long_peeler_model'+str(current_ring), 'out_2': 'long_unpeeled_sky'+str(current_ring)}])
    ####################################

    ####################################
    #Solve for gains
    blocks.append([NumpyBlock(np.copy), {'in_1': 'jones_in', 'out_1': 'jones_in_peeler'+str(current_ring)}])
    blocks.append([
        GainSolveBlock(flags=stand_flags, eps=0.5, max_iterations=10, l2reg=0.0),
        {'in_data': 'long_unpeeled_sky'+str(current_ring), 'in_model': 'long_peeler_model'+str(current_ring),
         'in_jones': 'jones_in_peeler'+str(current_ring), 'out_data': 'trash_peel'+str(current_ring),
         'out_jones': 'peeled_jones_out'+str(current_ring)}])
    ####################################
    current_ring += 1

########################################
#Average all solutions and apply to raw data
def array_average(*arrays):
    """Average all arrays inputted"""
    return np.average(arrays, axis=0)

solution_rings = {'in_%d'%(i+1): 'peeled_jones_out'+str(i) for i in range(total_sources-1)}
solution_rings['in_%d'%(total_sources)] = 'jones_out'+str(total_sources-1)
averaging_rings = solution_rings
averaging_rings['out_1'] = 'average_jones'
blocks.append([NumpyBlock(array_average, inputs=total_sources), averaging_rings])
blocks.append([
    NumpyBlock(apply_gains, inputs=2),
    {'in_1': 'clean_formatted_visibilities', 'in_2': 'average_jones',
     'out_1': 'calibrated_peeled_solution'}])
########################################

########################################
#Image the visibilities and get the uv coordinates
view = 'calibrated_peeled_solution'
blocks.append((
    NumpyBlock(reformat_data_for_gridding, inputs=2),
    {'in_1': view, 'in_2': 'uv_coords', 'out_1': view+'_data_for_gridding'}))
blocks.append((
    NearestNeighborGriddingBlock((256, 256)),
    [view+'_data_for_gridding'], [view+'_grid']))
blocks.append((IFFT2Block(), [view+'_grid'], [view+'_image']))
########################################

########################################
#Create an image with a horizon circle overlay'd
def image_horizon(image_array):
    """Image the horizon of an image"""
    center_pixel = np.array((image_array.shape[0]/2,)*2)
    superimposed_array = np.copy(image_array)
    indices = np.indices(image_array.shape)
    x_distance = indices[0, :, :] - center_pixel[0]
    y_distance = indices[1, :, :] - center_pixel[1]
    distance = np.abs(x_distance+1j*y_distance)
    horizon = np.abs(distance-PIXEL_DIAMETER_PER_MHZ*frequencies[0]/2e6) < 1
    superimposed_array[horizon] = np.max(np.abs(image_array))
    return superimposed_array

blocks.append([NumpyBlock(image_horizon), {'in_1': view+'_image', 'out_1': 'final_image'}])
blocks.append([ImagingBlock('sky.png', np.abs, log=False), {'in': 'final_image'}])
########################################

########################################
#Print image statistics
def print_stats(array):
    print "SNR:", np.max(np.abs(array))/np.average(np.abs(array))

def print_all_stats(*arrays):
    #assert np.average(arrays[0]) != np.average(arrays[1])
    for i in range(len(arrays)):
        array = np.abs(arrays[i].ravel())
        foreground_array = np.sort(array)[int(0.75*array.size):]
        background_array = np.sort(array)[:int(0.75*array.size)]
        print "Stats for %d peel"%(i)
        print "Max of foreground:", np.max(np.abs(foreground_array))
        print "Min of foreground:", np.min(np.abs(foreground_array))
        print "Mean of foreground:", np.average(np.abs(foreground_array))
        print "Stdev of foreground:", np.std(np.abs(foreground_array))
        print "RMS of foreground:", np.sqrt(np.sum(np.square(np.abs(foreground_array))/foreground_array.size))
        print "Max of background:", np.max(np.abs(background_array))
        print "Min of background:", np.min(np.abs(background_array))
        print "Mean of background:", np.average(np.abs(background_array))
        print "Stdev of background:", np.std(np.abs(background_array))
        print "RMS of background:", np.sqrt(np.sum(np.square(np.abs(background_array))/background_array.size))
        print " "

#blocks.append([NumpyBlock(print_stats, outputs=0), {'in_1': view+'_image'}])
#blocks.append([NumpyBlock(print_all_stats, inputs=1, outputs=0),
    #{'in_1': view+'_image'}])
########################################

Pipeline(blocks).main()
