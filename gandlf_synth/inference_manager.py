import os
import numpy as np
import pandas as pd

import torch
from torch.utils.data import DataLoader

from gandlf_synth.models.configs.config_abc import AbstractModelConfig
from gandlf_synth.models.modules.module_factory import ModuleFactory
from gandlf_synth.data.datasets_factory import DatasetFactory
from gandlf_synth.data.dataloaders_factory import DataloaderFactory
from gandlf_synth.metrics import get_metrics
from gandlf_synth.utils.managers_utils import (
    prepare_logger,
    prepare_postprocessing_transforms,
    prepare_transforms,
    assert_input_correctness,
)
from gandlf_synth.utils.io_utils import save_single_image

from typing import Optional, Type, Tuple


class InferenceManager:
    LOGGER_NAME = "InferenceManager"

    """Class to manage the inference of the model on the input data."""

    def __init__(
        self,
        global_config: dict,
        model_config: Type[AbstractModelConfig],
        model_dir: str,
        output_dir: str,
        device: str,
        dataframe_reconstruction: Optional[pd.DataFrame] = None,
        custom_checkpoint_suffix: Optional[str] = None,
    ) -> None:
        """Initialize the InferenceManager.

        Args:
            global_config (dict): The global configuration dictionary.
            model_config (Type[AbstractModelConfig]): The model configuration class.
            model_dir (str): The directory of the run where the target model is saved.
            output_dir (str): The top directory where the output files will be saved. The
            inference results will be saved in a subdirectory of this directory, with name equal
            to the model_dir basename.
            device (str, optional): The device to use for inference.
            dataframe_reconstruction (Optional[pd.DataFrame], optional): The dataframe with the data
        to perform reconstruction on. This will be used only for autoencoder-style models.
            custom_checkpoint_suffix (Optional[str], optional): The custom suffix for the checkpoint,
        mostly used when the model is to be loaded from specific epoch checkpoint.
        """

        self.global_config = global_config
        self.model_config = model_config
        self.model_dir = model_dir
        self.output_dir = self._prepare_output_directory(output_dir, model_dir)
        self.device = device
        self.dataframe_reconstruction = dataframe_reconstruction
        self._validate_inference_config()
        self.logger = prepare_logger(self.LOGGER_NAME)
        self.metric_calculator = (
            get_metrics(global_config["metrics"])
            if "metrics" in global_config
            else None
        )

        module_factory = ModuleFactory(
            model_config=self.model_config,
            logger=self.logger,
            device=self.device,
            model_dir=self.model_dir,
            postprocessing_transforms=prepare_postprocessing_transforms(
                global_config=self.global_config
            ),
        )
        self.module = module_factory.get_module()
        self.module.load_checkpoint(custom_checkpoint_suffix)
        # ensure model in eval mode
        self.module.model.eval()
        if self.dataframe_reconstruction is not None:
            self.dataloader = self._prepare_inference_dataloader()

    @staticmethod
    def _prepare_output_directory(output_dir: str, model_dir: str) -> str:
        """
        Prepare the output directory to save inference results. If the directory
        does not exist, it will be created. If it exists, new directory will be
        created with a new index.
        """

        def _prepare_out_dir_path(output_dir: str, model_dir: str) -> str:
            """
            Prepare the save path for the inference results by merging the output
            directory and the model directory name.

            Args:
                output_dir (str): The output directory.
                model_dir (str): The model directory name.

            Returns:
                str: The save path for the inference results.
            """
            return os.path.join(
                output_dir, os.path.basename(model_dir) + "_inference_output"
            )

        model_inference_output_path = _prepare_out_dir_path(output_dir, model_dir)

        if not os.path.exists(model_inference_output_path):
            os.makedirs(model_inference_output_path)
            return model_inference_output_path

        index = 1
        while os.path.exists(f"{model_inference_output_path}_{index}"):
            index += 1
        model_inference_output_path = f"{model_inference_output_path}_{index}"
        os.makedirs(model_inference_output_path)
        return model_inference_output_path

    def _prepare_inference_dataloader(self) -> DataLoader:
        """
        Prepare the dataloader for the inference process if reconstruction
        data is provided.

        Returns:
            torch.utils.data.DataLoader: The dataloader for the inference process.
        """
        transforms = prepare_transforms(
            augmentations_config=self.global_config.get("augmentations"),
            preprocessing_config=self.global_config.get("preprocessing"),
            mode="inference",
            input_shape=self.model_config.input_shape,
        )
        dataset_factory = DatasetFactory()
        dataloader_factory = DataloaderFactory(params=self.global_config)
        dataset = dataset_factory.get_dataset(
            self.dataframe_reconstruction,
            transforms,
            labeling_paradigm=self.model_config.labeling_paradigm,
        )
        dataloader = dataloader_factory.get_inference_dataloader(dataset=dataset)
        return dataloader

    # TODO: probably needs extension in the future
    def _validate_inference_config(self):
        """
        Validate the inference config.
        """
        inference_config: dict = self.global_config.get("inference_parameters")
        assert (
            "n_images_to_generate" in inference_config.keys()
        ), "The inference config for the unlabeled paradigm must contain the key 'n_images_to_generate'."
        if self.model_config.labeling_paradigm == "unlabeled":
            assert isinstance(
                inference_config["n_images_to_generate"], int
            ), "The number of images to generate must be an integer."
            assert (
                inference_config["n_images_to_generate"] > 0
            ), "The number of images to generate must be greater than 0."
        else:
            assert isinstance(
                inference_config["n_images_to_generate"], dict
            ), "The number of images to generate must be a dictionary."
            for class_label, n_images in inference_config[
                "n_images_to_generate"
            ].items():
                assert isinstance(
                    n_images, int
                ), "The number of images to generate must be an integer."
                assert (
                    n_images > 0
                ), "The number of images to generate must be greater than 0."

    @staticmethod
    def _determine_n_batches(
        n_images_to_generate: int, batch_size: int
    ) -> Tuple[int, int]:
        """
        Determine the number of batches needed to generate the images.

        Args:
            n_images_to_generate (int): The number of images to generate.
            batch_size (int): The batch size.

        Returns:
            Tuple[int, int]: The number of batches and the remainder.
        """
        n_batches = n_images_to_generate // batch_size
        remainder = n_images_to_generate % batch_size
        if remainder > 0:
            n_batches += 1
        return n_batches, remainder

    def _prepare_images_for_saving(self, generated_images: torch.Tensor) -> np.ndarray:
        """
        Prepare the generated images for saving.

        Args:
            generated_images (torch.Tensor): The generated images.

        Returns:
            np.ndarray: The generated images prepared for saving.
        """
        if self.model_config.n_dimensions == 2:
            generated_images = generated_images.permute(0, 2, 3, 1)
        elif self.model_config.n_dimensions == 3:
            generated_images = generated_images.permute(0, 2, 3, 4, 1)

        return generated_images.cpu().numpy()

    def _unlabeled_inference(self, inference_config: dict):
        """
        Perform inference on the unlabeled data.

        Args:
            inference_config (dict): The inference configuration dictionary.
        """

        # get total images to generate and batch size
        n_images_to_generate = inference_config["n_images_to_generate"]
        self.logger.info(f"Generating {n_images_to_generate} images.")
        batch_size = self.global_config.get("batch_size", 1)
        n_batches, remainder = self._determine_n_batches(
            n_images_to_generate, batch_size
        )
        # determine how many batches are needed

        # generate the images
        for i in range(n_batches):
            n_images_batch = batch_size
            if remainder > 0 and i == n_batches - 1:
                n_images_batch = remainder
            inference_step_kwargs = {"n_images_to_generate": n_images_batch}
            generated_images = self.module.inference_step(**inference_step_kwargs)
            generated_images = self._prepare_images_for_saving(generated_images)
            # TODO can we make it distributed? Would be much faster
            for j, generated_image in enumerate(generated_images):
                image_path = os.path.join(
                    self.output_dir, f"generated_image_{i * batch_size + j}"
                )
                save_single_image(
                    generated_image,
                    image_path,
                    self.global_config["modality"],
                    self.model_config.n_dimensions,
                )

    def _labeled_inference(self, inference_config: dict):
        """
        Perform inference on the labeled data.

        Args:
            inference_config (dict): The inference configuration dictionary.
        """

        per_class_n_images_to_generate = inference_config["n_images_to_generate"]
        for class_label, n_images_to_generate in per_class_n_images_to_generate.items():
            self.logger.info(
                f"Generating {n_images_to_generate} images for class {class_label}."
            )
            # determine how many batches are needed
            batch_size = self.global_config.get("batch_size", 1)

            n_batches, remainder = self._determine_n_batches(
                n_images_to_generate, batch_size
            )
            # generate the images
            for i in range(n_batches):
                n_images_batch = batch_size
                if remainder > 0 and i == n_batches - 1:
                    n_images_batch = remainder
                inference_step_kwargs = {
                    "n_images_to_generate": n_images_batch,
                    "class_label": class_label,
                }
                generated_images = self.module.inference_step(**inference_step_kwargs)
                generated_images = self._prepare_images_for_saving(generated_images)
                for j, generated_image in enumerate(generated_images):
                    image_path = os.path.join(
                        self.output_dir,
                        f"generated_image_{i * batch_size + j}_class_{class_label}",
                    )
                    save_single_image(
                        generated_image,
                        image_path,
                        self.global_config["modality"],
                        self.model_config.n_dimensions,
                    )

    def run_inference(self):
        """
        Perform inference on the data.
        """
        self.logger.info("Starting inference.")
        inference_config = self.global_config["inference_parameters"]
        # TODO think about some strategy pattern here
        if self.model_config.labeling_paradigm == "unlabeled":
            self._unlabeled_inference(inference_config)
        else:
            self._labeled_inference(inference_config)
        self.logger.info("Inference finished.")
