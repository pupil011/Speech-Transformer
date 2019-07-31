import numpy as np
import torch
from tensorboardX import SummaryWriter
from torch import nn

from config import device, grad_clip, print_freq, vocab_size, num_workers, sos_id, eos_id
from data_gen import AiShellDataset, pad_collate
from transformer.decoder import Decoder
from transformer.encoder import Encoder
from transformer.transformer import Transformer
from utils import parse_args, save_checkpoint, AverageMeter, clip_gradient, get_logger


def train_net(args):
    torch.manual_seed(7)
    np.random.seed(7)
    checkpoint = args.checkpoint
    start_epoch = 0
    best_loss = float('inf')
    writer = SummaryWriter()
    epochs_since_improvement = 0

    # Initialize / load checkpoint
    if checkpoint is None:
        # model
        encoder = Encoder(args.d_input * args.LFR_m, args.n_layers_enc, args.n_head,
                          args.d_k, args.d_v, args.d_model, args.d_inner,
                          dropout=args.dropout, pe_maxlen=args.pe_maxlen)
        decoder = Decoder(sos_id, eos_id, vocab_size,
                          args.d_word_vec, args.n_layers_dec, args.n_head,
                          args.d_k, args.d_v, args.d_model, args.d_inner,
                          dropout=args.dropout,
                          tgt_emb_prj_weight_sharing=args.tgt_emb_prj_weight_sharing,
                          pe_maxlen=args.pe_maxlen)
        model = Transformer(encoder, decoder)
        # model = nn.DataParallel(model)

        optimizer = torch.optim.Adam(model.parameters(), betas=(0.9, 0.98), eps=1e-09)

    else:
        checkpoint = torch.load(checkpoint)
        start_epoch = checkpoint['epoch'] + 1
        epochs_since_improvement = checkpoint['epochs_since_improvement']
        model = checkpoint['model']
        optimizer = checkpoint['optimizer']

    logger = get_logger()

    # Move to GPU, if available
    model = model.to(device)

    # Custom dataloaders
    train_dataset = AiShellDataset('train')
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, collate_fn=pad_collate,
                                               shuffle=True, num_workers=num_workers)
    valid_dataset = AiShellDataset('dev')
    valid_loader = torch.utils.data.DataLoader(valid_dataset, batch_size=args.batch_size, collate_fn=pad_collate,
                                               shuffle=False, num_workers=num_workers, drop_last=True)

    # Epochs
    for epoch in range(start_epoch, args.end_epoch):
        # One epoch's training
        train_loss = train(train_loader=train_loader,
                           model=model,
                           optimizer=optimizer,
                           epoch=epoch,
                           logger=logger)
        writer.add_scalar('Train_Loss', train_loss, epoch)
        logger.info('[Training] Accuracy : {:.4f}'.format(train_loss))

        # One epoch's validation
        valid_loss = valid(valid_loader=valid_loader,
                           model=model)
        writer.add_scalar('Valid_Loss', valid_loss, epoch)
        logger.info('[Validate] Accuracy : {:.4f}'.format(valid_loss))

        # Check if there was an improvement
        is_best = valid_loss < best_loss
        best_loss = min(valid_loss, best_loss)
        if not is_best:
            epochs_since_improvement += 1
            print("\nEpochs since last improvement: %d\n" % (epochs_since_improvement,))
        else:
            epochs_since_improvement = 0

        # Save checkpoint
        save_checkpoint(epoch, epochs_since_improvement, model, optimizer, best_loss, is_best)


def train(train_loader, model, optimizer, epoch, logger):
    model.train()  # train mode (dropout and batchnorm is used)

    losses = AverageMeter()

    # Batches
    for i, (data) in enumerate(train_loader):
        # Move to GPU, if available
        padded_input, padded_target, input_lengths = data
        print('padded_input.size(): ' + str(padded_input.size()))
        print('input_lengths.size(): ' + str(input_lengths.size()))
        print('padded_target.size(): ' + str(padded_target.size()))
        print('type(padded_input): ' + str(type(padded_input)))
        print('type(input_lengths): ' + str(type(input_lengths)))
        print('type(padded_target): ' + str(type(padded_target)))
        print('padded_input: ' + str(padded_input))
        print('input_lengths: ' + str(input_lengths))
        print('padded_target: ' + str(padded_target))
        padded_input = padded_input.to(device)
        padded_target = padded_target.to(device)
        input_lengths = input_lengths.to(device)

        # Forward prop.
        loss = model(padded_input, input_lengths, padded_target)

        # Back prop.
        optimizer.zero_grad()
        loss.backward()

        # Clip gradients
        clip_gradient(optimizer, grad_clip)

        # Update weights
        optimizer.step()

        # Keep track of metrics
        losses.update(loss.item())

        # Print status
        if i % print_freq == 0:
            logger.info('Epoch: [{0}][{1}/{2}]\t'
                        'Loss {loss.val:.4f} ({loss.avg:.4f})'.format(epoch, i, len(train_loader), loss=losses))

    return losses.avg


def valid(valid_loader, model):
    model.eval()

    losses = AverageMeter()

    # Batches
    for i, (features, trns, input_lengths) in enumerate(valid_loader):
        # Move to GPU, if available
        features = features.float().to(device)
        trns = trns.long().to(device)
        input_lengths = input_lengths.long().to(device)

        # Forward prop.
        loss = model(features, input_lengths, trns)

        # Keep track of metrics
        losses.update(loss.item())

    return losses.avg


def main():
    global args
    args = parse_args()
    train_net(args)


if __name__ == '__main__':
    main()
