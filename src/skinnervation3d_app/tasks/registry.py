from typing import Any, Callable, List
from mesospim_fractal_tasks.tasks import (crop_regions_of_interest_dask,
                                          correct_flatfield_dask,
                                          correct_illumination_dask,
                                          stitch_with_multiview_stitcher,
                                          mesospim_to_omezarr,
                                          modify_omezarr_structure,
                                          prepare_mesospim_omezarr)
from skinnervation3d_fractal_tasks.tasks import (fit_surface,
                                                 segment_fibers_dask,
                                                 analyse_fiber_plexus,
                                                 compute_fiber_density_per_structure_dask,
                                                 count_number_fiber_crossing_dask,
                                                 export_results)
from skinnervation3d_app.tasks.spec import TaskSpec, build_task_specs


PREPROCESSING_TASK_FUNCTIONS: List[Callable[..., Any]] = [
    mesospim_to_omezarr.mesospim_to_omezarr,
    prepare_mesospim_omezarr.prepare_mesospim_omezarr,
    correct_flatfield_dask.correct_flatfield,
    crop_regions_of_interest_dask.crop_regions_of_interest,
    correct_illumination_dask.correct_illumination,
    stitch_with_multiview_stitcher.stitch_with_multiview_stitcher,
    modify_omezarr_structure.modify_omezarr_structure,
]

ANALYSIS_TASK_FUNCTIONS: List[Callable[..., Any]] = [
    fit_surface.fit_surface,
    segment_fibers_dask.segment_fibers,
    count_number_fiber_crossing_dask.count_number_fiber_crossing,
    compute_fiber_density_per_structure_dask.compute_fiber_density_per_structure,
    export_results.export_results
    #analyse_fiber_plexus.analyse_fiber_plexus,
]

PRE_TASKS: List[TaskSpec] = build_task_specs(
    PREPROCESSING_TASK_FUNCTIONS, category="preprocessing")
ANALYSIS_TASKS: List[TaskSpec] = build_task_specs(
    ANALYSIS_TASK_FUNCTIONS, category="analysis")
TASKS: List[TaskSpec] = PRE_TASKS + ANALYSIS_TASKS
