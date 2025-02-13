import os

import torch
from torch import nn, optim
from torchvision.utils import save_image

from gandlf_synth.models.architectures.base_model import ModelBase
from gandlf_synth.models.architectures.dcgan import DCGAN
from gandlf_synth.models.modules.module_abc import SynthesisModule
from gandlf_synth.optimizers import get_optimizer
from gandlf_synth.losses import get_loss
from gandlf_synth.schedulers import get_scheduler

from typing import Dict, Union, List


class UnlabeledDCGANModule(SynthesisModule):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model: DCGAN
        self.automatic_optimization = False
        self.train_loss_list: List[Dict[float]] = []

    def training_step(self, batch: object, batch_idx: int) -> torch.Tensor:
        real_images: torch.Tensor = batch

        # those are used for gradient accumulation and clipping
        # defaults are set in the model config, by default we do not accumulate gradients
        # nor clip them
        gardient_accumulation_steps = self.model_config.accumulate_grad_batches
        gradient_clip_val = self.model_config.gradient_clip_val
        gradient_clip_algorithm = self.model_config.gradient_clip_algorithm

        batch_size = real_images.shape[0]
        latent_vector = self._generate_latent_vector(batch_size).type_as(real_images)
        loss_disc, loss_gen = self.losses["disc_loss"], self.losses["gen_loss"]
        optimizer_disc, optimizer_gen = self.optimizers()

        # GENERATOR PASS
        self.toggle_optimizer(optimizer_gen)
        fake_images = self.model.generator(latent_vector)
        label_real = torch.ones(real_images.size(0), 1).type_as(real_images)
        gen_loss = (
            loss_gen(self.model.discriminator(fake_images), label_real)
            / gardient_accumulation_steps
        )
        self.manual_backward(gen_loss)
        self.clip_gradients(
            optimizer_gen,
            gradient_clip_val=gradient_clip_val,
            gradient_clip_algorithm=gradient_clip_algorithm,
        )
        if (batch_idx + 1) % gardient_accumulation_steps == 0:
            optimizer_gen.step()
            optimizer_gen.zero_grad(set_to_none=True)

        self.untoggle_optimizer(optimizer_gen)

        # DISCRIMINATOR PASS
        self.toggle_optimizer(optimizer_disc)
        # real labels
        label_real = torch.ones(real_images.size(0), 1).type_as(real_images)
        # fake labels
        label_fake = torch.zeros(real_images.size(0), 1).type_as(real_images)
        # get the predictions and calculate the loss for the real images
        preds_real = self.model.discriminator(real_images)
        disc_loss_real = loss_disc(preds_real, label_real)
        # get the predictions and calculate the loss for the fake images
        disc_loss_fake = loss_disc(
            self.model.discriminator(fake_images.detach()), label_fake
        )
        # calculate the total loss
        total_disc_loss = (disc_loss_real + disc_loss_fake) / 2
        self.manual_backward(total_disc_loss)

        self.clip_gradients(
            optimizer_disc,
            gradient_clip_val=self.model_config.gradient_clip_val,
            gradient_clip_algorithm=self.model_config.gradient_clip_algorithm,
        )

        if (batch_idx + 1) % gardient_accumulation_steps == 0:
            optimizer_disc.step()
            optimizer_disc.zero_grad(set_to_none=True)

        self.untoggle_optimizer(optimizer_disc)
        loss_dict = {"disc_loss": total_disc_loss.item(), "gen_loss": gen_loss.item()}
        self._step_log(loss_dict)
        self.train_loss_list.append(loss_dict)

        if self.metric_calculator is not None:
            metric_results = {}
            for metric_name, metric in self.metric_calculator.items():
                metric_results[metric_name] = metric(real_images, fake_images.detach())
            self._step_log(metric_results)

    def validation_step(self, batch: object, batch_idx: int) -> torch.Tensor:
        raise NotImplementedError("Validation step is not implemented for the DCGAN.")

    def test_step(self, batch: object, batch_idx: int) -> torch.Tensor:
        raise NotImplementedError("Test step is not implemented for the DCGAN.")

    def predict_step(self, batch, batch_dx) -> torch.Tensor:
        n_images_to_generate = len(batch)
        latent_vector = self._generate_latent_vector(n_images_to_generate)
        fake_images = self.model.generator(latent_vector)
        if self.postprocessing_transforms is not None:
            for transform in self.postprocessing_transforms:
                fake_images = transform(fake_images)
        # DCGAN will produce images in the range [-1, 1], we need to normalize them to [0, 1]
        fake_images = (fake_images + 1) / 2

        return fake_images

    def forward(self, latent_vector) -> torch.Tensor:
        """
        Forward pass of the unlabeled DCGAN module.
        Args:
            latent_vector (torch.Tensor): The latent vector to generate the images from.

        Returns:
            torch.Tensor: The generated fake images.
        """

        fake_images = self.model.generator(latent_vector)
        return fake_images

    def _initialize_model(self) -> ModelBase:
        return DCGAN(self.model_config)

    def _initialize_losses(self) -> Union[nn.Module, Dict[str, nn.Module]]:
        disc_loss = get_loss(self.model_config.losses["discriminator"])
        gen_loss = get_loss(self.model_config.losses["generator"])
        return {"disc_loss": disc_loss, "gen_loss": gen_loss}

    @staticmethod
    def _initialize_scheduler(
        disc_optimizer: optim.Optimizer,
        gen_optimizer: optim.Optimizer,
        schedulers_config: dict,
    ) -> Union[Dict[str, Union[optim.lr_scheduler._LRScheduler, None]]]:
        disc_scheduler, gen_scheduler = None, None

        # currently, there is no option of using scheduler for only
        # one of the optimizers. Either need to specify one scheduler for
        # both optimizers or two separate schedulers for each optimizer.

        if "discriminator" in schedulers_config or "generator" in schedulers_config:
            assert (
                "discriminator" in schedulers_config
                and "generator" in schedulers_config
            ), "If you want to use different schedulers for discriminator and generator, you need to specify both."
            disc_scheduler = get_scheduler(
                disc_optimizer, schedulers_config["discriminator"]
            )
            gen_scheduler = get_scheduler(gen_optimizer, schedulers_config["generator"])
        # case when the same scheduler is used for both optimizers
        else:
            disc_scheduler = get_scheduler(disc_optimizer, schedulers_config)
            gen_scheduler = get_scheduler(gen_optimizer, schedulers_config)
        return {"disc_scheduler": disc_scheduler, "gen_scheduler": gen_scheduler}

    def configure_optimizers(self):
        disc_optimizer = get_optimizer(
            model_params=self.model.discriminator.parameters(),
            optimizer_parameters=self.model_config.optimizers["discriminator"],
        )
        gen_optimizer = get_optimizer(
            model_params=self.model.generator.parameters(),
            optimizer_parameters=self.model_config.optimizers["generator"],
        )
        if self.model_config.schedulers is not None:
            schedulers = self._initialize_scheduler(
                disc_optimizer, gen_optimizer, self.model_config.schedulers
            )
            return [disc_optimizer, gen_optimizer], [
                schedulers["disc_scheduler"],
                schedulers["gen_scheduler"],
            ]

        return [disc_optimizer, gen_optimizer]

    def _generate_latent_vector(self, batch_size: int) -> torch.Tensor:
        latent_vector = torch.randn(
            (batch_size, self.model_config.architecture["latent_vector_size"], 1, 1),
            device=self.device,
        )
        if self.model_config.n_dimensions == 3:
            latent_vector = latent_vector.unsqueeze(-1)
        return latent_vector

    def _generate_fixed_latent_vector(self, batch_size: int) -> torch.Tensor:
        current_rng_state = torch.get_rng_state()
        torch.manual_seed(self.model_config.fixed_latent_vector_seed)
        latent_vector = self._generate_latent_vector(batch_size)
        torch.set_rng_state(current_rng_state)
        return latent_vector

    def _generate_image_set_from_fixed_vector(
        self, n_images_to_generate
    ) -> torch.Tensor:
        fixed_latent_vector = self._generate_fixed_latent_vector(n_images_to_generate)
        fake_images = self.model.generator(fixed_latent_vector)
        return fake_images

    # TODO this should be extracted in general to a separate class perhaps
    def on_train_epoch_end(self) -> None:
        self._epoch_log(self.train_loss_list)

        process_rank = self.global_rank
        eval_save_interval = self.model_config.save_eval_images_every_n_epochs
        dimension = self.model_config.n_dimensions  # only for 2d
        if (
            dimension == 2
            and eval_save_interval > 0
            and self.current_epoch % eval_save_interval == 0
        ):
            fixed_images_save_path = os.path.join(
                self.model_dir, f"eval_images", f"epoch_{self.current_epoch}"
            )
            if not os.path.exists(fixed_images_save_path):
                os.makedirs(fixed_images_save_path, exist_ok=True)
            last_batch_size = (
                self.model_config.n_fixed_images_to_generate
                % self.model_config.fixed_images_batch_size
            )
            n_batches = (
                self.model_config.n_fixed_images_to_generate
                // self.model_config.fixed_images_batch_size
            )
            if last_batch_size > 0:
                n_batches += 1
            for i in range(n_batches):
                n_images_to_generate = self.model_config.fixed_images_batch_size
                if (i == n_batches - 1) and last_batch_size > 0:
                    n_images_to_generate = last_batch_size
                fake_images = self._generate_image_set_from_fixed_vector(
                    n_images_to_generate
                )
                for n, fake_image in enumerate(fake_images):
                    save_image(
                        fake_image,
                        os.path.join(
                            fixed_images_save_path,
                            f"fake_image_{i*n + n}_{process_rank}.png",
                        ),
                        normalize=True,
                    )
