from typing import Any, Callable, List
from mesospim_fractal_tasks.tasks import (crop_regions_of_interest_dask,
                                          correct_flatfield_dask,
                                          correct_illumination_dask,
                                          stitch_with_multiview_stitcher, 
                                          mesospim_to_omezarr)
from skinnervation3d_fractal_tasks.tasks import (fit_surface,
                                                 segment_fibers,
                                                 analyse_fiber_plexus,
                                                 compute_fiber_density_per_structure,
                                                 count_number_fiber_crossing)
from skinnervation3d_app.tasks.spec import TaskSpec, build_task_specs


PREPROCESSING_TASK_FUNCTIONS: List[Callable[..., Any]] = [
    mesospim_to_omezarr.mesospim_to_omezarr,
    crop_regions_of_interest_dask.crop_regions_of_interest,
    correct_flatfield_dask.correct_flatfield,
    correct_illumination_dask.correct_illumination,
    stitch_with_multiview_stitcher.stitch_with_multiview_stitcher
]

ANALYSIS_TASK_FUNCTIONS: List[Callable[..., Any]] = [
    fit_surface.fit_surface,
    segment_fibers.segment_fibers,
    count_number_fiber_crossing.count_number_fiber_crossing,
    compute_fiber_density_per_structure.compute_fiber_density_per_structure,
    analyse_fiber_plexus.analyse_fiber_plexus,
]

PRE_TASKS: List[TaskSpec] = build_task_specs(
    PREPROCESSING_TASK_FUNCTIONS, category="preprocessing")
ANALYSIS_TASKS: List[TaskSpec] = build_task_specs(
    ANALYSIS_TASK_FUNCTIONS, category="analysis")
TASKS: List[TaskSpec] = PRE_TASKS + ANALYSIS_TASKS