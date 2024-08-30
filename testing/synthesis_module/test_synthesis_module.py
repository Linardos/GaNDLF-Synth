import os
import yaml
import inspect
import logging
from pathlib import Path

import pandas as pd
from torchio.transforms import Compose, Resize
import pytorch_lightning as pl
from gandlf_synth.config_manager import ConfigManager
from gandlf_synth.data.datasets_factory import DatasetFactory
from gandlf_synth.data.dataloaders_factory import DataloaderFactory
from gandlf_synth.models.modules.module_factory import ModuleFactory
from gandlf_synth.training_manager import TrainingManager
from gandlf_synth.inference_manager import InferenceManager
from testing.testing_utils import ContextManagerTests

TEST_DIR = Path(__file__).parent.absolute().__str__()
OUTPUT_DIR = os.path.join(TEST_DIR, "output")
INFERENCE_OUTPUT_DIR = os.path.join(TEST_DIR, "inference_output")
LOG_DIR = os.path.join(TEST_DIR, "logs")

CSV_PATH = os.path.join(os.path.dirname(TEST_DIR), "unlabeled_data.csv")
DEVICE = "cpu"
BASIC_LOGGER_CONFIG = logging.basicConfig(
    filename=f"{LOG_DIR}/synthesis_module_tests.log",
    filemode="w",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level="INFO",
)
LOGGER_OBJECT = logging.getLogger("synthesis_module_logger")

# Take all available modules registered
AVAILABLE_MODULES = list(ModuleFactory.AVAILABE_MODULES.keys())
# Take all available model configs registered
AVAILABLE_CONFIGS = list(ModuleFactory.AVAILABE_MODULES.keys())

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


def test_module_config_pairs():
    # Check if all available modules have a corresponding config and vice versa
    for module in AVAILABLE_MODULES:
        assert (
            module in AVAILABLE_CONFIGS
        ), f"Module {module} does not have a corresponding config"
    for config in AVAILABLE_CONFIGS:
        assert (
            config in AVAILABLE_MODULES
        ), f"Config {config} does not have a corresponding module"


# TODO: This test is checking the pipeline created manually, wtihout encampsulating it in
# a training manager. For now it is commented out, as the same logic happens in training manager
# in the future we may remove it or replace it with some modification.


# def test_initial_pipeline_module():
#     test_name = inspect.currentframe().f_code.co_name
#     with ContextManagerTests(
#         test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
#     ):
#         for module in AVAILABLE_MODULES:
#             # labeling_paradigm, model_name = parse_available_module(module)
#             with open(TEST_CONFIG_PATH, "r") as config_file:
#                 config = yaml.safe_load(config_file)
#                 # config["model_config"]["model_name"] = model_name
#                 # config["model_config"]["labeling_paradigm"] = labeling_paradigm
#             with open(TEST_CONFIG_PATH, "w") as config_file:
#                 yaml.dump(config, config_file)
#             config_manager = ConfigManager(TEST_CONFIG_PATH)

#             global_config, model_config = config_manager.prepare_configs()
#             # TODO this needs to be replaced with proper transforms
#             RESIZE_TRANSFORM = Compose([Resize((128, 128, 1))])
#             dataset_factory = DatasetFactory()
#             dataloader_factory = DataloaderFactory(global_config)
#             example_dataframe = pd.read_csv(CSV_PATH)
#             dataset = dataset_factory.get_dataset(
#                 example_dataframe, RESIZE_TRANSFORM, model_config.labeling_paradigm
#             )

#             dataloader = dataloader_factory.get_training_dataloader(dataset)

#             module_factory = ModuleFactory(
#                 model_config=model_config,
#                 logger=LOGGER_OBJECT,
#                 metric_calculator=None,
#                 model_dir=OUTPUT_DIR,
#             )
#             module = module_factory.get_module()

#             trainer = pl.Trainer(max_epochs=1)
#             trainer.fit(module, dataloader)


#             for batch_idx, batch in enumerate(dataloader):
#                 module.training_step(batch, batch_idx)
#                 print("Training step completed!")
#                 break


def test_training_manager_val_test_df():
    """
    Test with val and test dataframes provided for splitting the data.
    """
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_vqvae.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        global_config, model_config = config_manager.prepare_configs()
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
            val_dataframe=example_dataframe,
            test_dataframe=example_dataframe,
        )
        training_manager.run_training()


def test_training_manager_val_test_ratio():
    """
    Test with val and test ratio provided for splitting the data.
    """
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_vqvae.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        global_config, model_config = config_manager.prepare_configs()
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
            val_ratio=0.1,
            test_ratio=0.1,
        )
        training_manager.run_training()


def test_training_manager_val_test_fallback():
    """
    Test fallback to dataframes when both ratios and dataframes are provided.
    Should fallback to dataframes.
    """
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_vqvae.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
            val_ratio=0.1,
            test_ratio=0.1,
            val_dataframe=example_dataframe,
            test_dataframe=example_dataframe,
        )
        training_manager.run_training()


def test_training_manager_reset_resume():
    """
    Test resetting and resuming training.
    """
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_vqvae.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        # Test resetting and resuming
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
        )
        training_manager.run_training()
        global_config, model_config = config_manager.prepare_configs()
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=True,
        )
        training_manager.run_training()
        global_config, model_config = config_manager.prepare_configs()
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=True,
            reset=False,
        )
        training_manager.run_training()


def test_training_inference_dcgan():
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_dcgan.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
        )
        training_manager.run_training()
        inference_manager = InferenceManager(
            model_config=model_config,
            global_config=global_config,
            model_dir=OUTPUT_DIR,
            output_dir=INFERENCE_OUTPUT_DIR,
        )
        inference_manager.run_inference()


def test_training_inference_vqvae():
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_vqvae.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            val_dataframe=example_dataframe,
            test_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
        )
        training_manager.run_training()

        inference_manager = InferenceManager(
            global_config=global_config,
            model_config=model_config,
            model_dir=OUTPUT_DIR,
            output_dir=INFERENCE_OUTPUT_DIR,
            dataframe_reconstruction=example_dataframe,
        )
        inference_manager.run_inference()


def test_training_inference_ddpm():
    test_name = inspect.currentframe().f_code.co_name
    with ContextManagerTests(
        test_dir=TEST_DIR, test_name=test_name, output_dir=OUTPUT_DIR
    ):
        test_config_path = os.path.join(TEST_DIR, "syntheis_module_config_ddpm.yaml")
        config_manager = ConfigManager(test_config_path)
        global_config, model_config = config_manager.prepare_configs()
        example_dataframe = pd.read_csv(CSV_PATH)
        training_manager = TrainingManager(
            train_dataframe=example_dataframe,
            output_dir=OUTPUT_DIR,
            global_config=global_config,
            model_config=model_config,
            resume=False,
            reset=False,
        )
        training_manager.run_training()

        inference_manager = InferenceManager(
            global_config=global_config,
            model_config=model_config,
            model_dir=OUTPUT_DIR,
            output_dir=INFERENCE_OUTPUT_DIR,
        )
        inference_manager.run_inference()
