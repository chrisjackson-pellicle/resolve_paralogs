# Author: Alexander Schmidt-Lebuhn (modified by Chris Jackson July 2021 chris.jackson@rbg.vic.gov.au)
# https://github.com/chrisjackson-pellicle

"""
Takes a newick tree and a fasta alignment as input. Returns a fasta alignment containing only the sequences
corresponding to the tree tip names.
"""

from Bio import AlignIO
from Bio import Phylo
import Bio.Align
import glob
import os
import sys
import textwrap
import shutil
import re

from paragone import utils


def subsample_alignments(treefile_directory,
                         tree_suffix,
                         alignment_directory,
                         from_cut_deep_paralogs=False,
                         algorithm_suffix=False,
                         logger=None):
    """
    Takes a pruned/QC'd tree file, finds the original matching alignment, and sub-samples that alignment to recover
    only sequences corresponding to tree tip names.

    :param str treefile_directory: path to directory containing tree newick files
    :param str tree_suffix: suffix for the tree files
    :param str alignment_directory: path to the directory containing fasta alignments
    :param bool from_cut_deep_paralogs: if True, process tree file names accordingly to recover gene names
    :param str algorithm_suffix: if extracting seqs from pruned trees, the algorithm suffix mo/rt/mi, else not_set
    :param logging.Logger logger: a logger object
    :return str, dict output_folder, alignment_filtering_dict: path the output folder with filtered alignments,
    dictionary of filtering stats for each tree/alignment
    """

    logger.info(f'{"[INFO]:":10} Recovering alignment sequences corresponding to tree tip names...')

    treefile_directory_basename = os.path.basename(treefile_directory)

    if from_cut_deep_paralogs:
        output_folder = f'11_{treefile_directory_basename.lstrip("10_")}_alignments'
    else:
        # output_folder = f'21_{re.sub("^[0-9]{2}_", "", treefile_directory_basename)}_alignments_{algorithm_suffix}'
        output_folder = f'21_selected_sequences_{algorithm_suffix}'


    utils.createfolder(output_folder)

    # Capture number of sequences pre and post filtering in a dictionary for report:
    alignment_filtering_dict = {}

    for tree in glob.glob(f'{treefile_directory}/*{tree_suffix}'):
        read_tree = Phylo.read(tree, "newick")
        tree_terminals = read_tree.get_terminals()
        tree_basename = os.path.basename(tree)

        # Derive the matching alignment file name depending on input tree file name:
        if from_cut_deep_paralogs:  # e.g. 4471_1.subtree
            alignment_prefix = '_'.join(tree_basename.split('_')[0:-1])
            output_alignment_prefix = tree_basename.split('.')[0]
            matching_alignment = f'{alignment_directory}/{alignment_prefix}.paralogs.aln.hmm.trimmed.fasta'
        else:  # e.g. 4691_1.1to1ortho.tre, 4471_1.inclade1.ortho1.tre, 4527_1.MIortho1.tre. etc
            alignment_prefix = tree_basename.split('.')[0]
            output_alignment_prefix = '.'.join(tree_basename.split('.')[0:-1])
            matching_alignment = f'{alignment_directory}/{alignment_prefix}.outgroup_added.aln.trimmed.fasta'

        # Read in original alignments and select seqs matching tree termini:
        alignment = AlignIO.read(matching_alignment, "fasta")
        subalignment = Bio.Align.MultipleSeqAlignment([])
        for k in range(0, len(alignment)):
            for j in range(0, len(tree_terminals)):
                if tree_terminals[j].name == alignment[k].id:
                    subalignment.append(alignment[k])

        # Capture data:
        alignment_filtering_dict[tree_basename] = [len(tree_terminals), len(alignment), len(subalignment)]

        # Write an alignment of the sub-selected sequences:
        AlignIO.write(subalignment, f'{output_folder}/{output_alignment_prefix}.selected.fasta', "fasta")

    return output_folder, alignment_filtering_dict


def batch_input_files(gene_fasta_directory,
                      output_directory,
                      batch_size=20,
                      algorithm_suffix=False,
                      logger=None):
    """
    Takes a folder of fasta files, and splits them in to batch folders according to the number provided by
    parameter batch_size.

    :param str gene_fasta_directory: path to input fasta files with sanitised filenames
    :param str output_directory: name of output directory to create
    :param int batch_size: number of fasta files per batch; default is 20
    :param bool/str algorithm_suffix: if not False, name of pruning method mo/rt/mi
    :param logging.Logger logger: a logger object
    :return:
    """

    utils.createfolder(output_directory)

    fill = textwrap.fill(f'{"[INFO]:":10} Fasta files of selected sequences will be split in to batches of size'
                         f' {batch_size}. Batch folders will be written to directory: '
                         f'"{output_directory}".',
                         width=90, subsequent_indent=' ' * 11, break_on_hyphens=False)
    logger.info(fill)

    fasta_file_list = glob.glob(f'{gene_fasta_directory}/*.fasta')

    def chunks(lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    batches = list(chunks(fasta_file_list, batch_size))
    batch_num = 1

    if algorithm_suffix:
        batch_prefix = f'{output_directory}/selected_batch_{algorithm_suffix}'
    else:
        batch_prefix = f'{output_directory}/selected_batch'

    for batch in batches:
        utils.createfolder(f'{batch_prefix}_{batch_num}')
        for fasta_file in batch:
            shutil.copy(fasta_file, f'{batch_prefix}_{batch_num}')
        batch_num += 1


def write_fasta_from_tree_report(alignment_filtering_dict,
                                 treefile_directory,
                                 from_cut_deep_paralogs,
                                 algorithm_suffix,
                                 logger=None):
    """
    Writes a *.tsv report detailing number of tips in QC'd tree, number of sequences in original QC'd alignment,
    and number of sequences in filtered alignment.

    :param dict alignment_filtering_dict: dictionary of filtering stats for each tree/alignment
    :param str treefile_directory: name of tree file directory for report filename
    :param bool from_cut_deep_paralogs: if True, add 'cut' to report filename
    :param str algorithm_suffix: if extracting seqs from pruned trees, the algorithm suffix mo/rt/mi, else not_set
    :param logging.Logger logger: a logger object
    :return:
    """

    basename = os.path.basename(treefile_directory)
    if from_cut_deep_paralogs:
        report_filename = f'00_logs_and_reports_resolve_paralogs/reports' \
                          f'/{basename.lstrip("10_")}_fasta_from_tree_report.tsv'
    else:
        # report_filename = f'00_logs_and_reports_resolve_paralogs/reports/' \
        #                   f'{re.sub("^[0-9]{2}_", "", basename)}_fasta_from_tree_{algorithm_suffix}_report.tsv'
        report_filename = f'00_logs_and_reports_resolve_paralogs/reports/fasta_from_tree_{algorithm_suffix}_report.tsv'

    logger.info(f'{"[INFO]:":10} Writing fasta from tree report to file {report_filename}')

    with open(report_filename, 'w') as report_handle:
        report_handle.write(f'QC tree file\tNumber of tree tips\tNumber seqs in original alignment\tNumber seqs '
                            f'filtered alignment\n')

        for tree_name, stats in alignment_filtering_dict.items():
            report_handle.write(f'{tree_name}\t{stats[0]}\t{stats[1]}\t{stats[2]}\n')


def main(args):
    """
    Entry point for the paragone_main.py script

    :param args: argparse namespace with subparser options for function main()
    :return:
    """

    algorithm_suffix = False

    # Initialise logger:
    if args.from_cut_deep_paralogs:
        logger = utils.setup_logger(__name__,
                                    '00_logs_and_reports_resolve_paralogs/logs/08_fasta_from_tree')
    elif args.from_prune_paralogs:
        algorithm_suffix = args.from_prune_paralogs
        logger = utils.setup_logger(__name__,
                                    f'00_logs_and_reports_resolve_paralogs/logs/14_fasta_from_tree_{algorithm_suffix}')

    # check for external dependencies:
    if utils.check_dependencies(logger=logger):
        logger.info(f'{"[INFO]:":10} All external dependencies found!')
    else:
        logger.error(f'{"[ERROR]:":10} One or more dependencies not found!')
        sys.exit(1)

    logger.info(f'{"[INFO]:":10} Subcommand fasta_from_tree was called with these arguments:')
    fill = textwrap.fill(' '.join(sys.argv[1:]), width=90, initial_indent=' ' * 11, subsequent_indent=' ' * 11,
                         break_on_hyphens=False)
    logger.info(f'{fill}\n')
    logger.debug(args)

    # Checking input directories and files:
    directory_suffix_dict = {args.treefile_directory: args.tree_file_suffix}
    file_list = []

    utils.check_inputs(directory_suffix_dict,
                       file_list,
                       logger=logger)

    # Create output folder:
    treefile_directory_basename = os.path.basename(args.treefile_directory)

    if args.from_cut_deep_paralogs:
        output_folder = f'12_{treefile_directory_basename.lstrip("10_")}_alignments_batches'
    elif args.from_prune_paralogs:
        # output_folder = f'21_{re.sub("^[0-9]{2}_", "", treefile_directory_basename)}_alignments_batches' \
        #                 f'_{algorithm_suffix}'
        output_folder = f'22_selected_sequences_{algorithm_suffix}_batches'

    utils.createfolder(output_folder)

    # Recover alignments with sequences corresponding to tree tip names:
    filtered_alignments_folder,  alignment_filtering_dict = \
        subsample_alignments(args.treefile_directory,
                             args.tree_file_suffix,
                             args.alignment_directory,
                             from_cut_deep_paralogs=args.from_cut_deep_paralogs,
                             algorithm_suffix=algorithm_suffix,
                             logger=logger)

    # Batch fasta files for alignment and tree-building steps:
    batch_input_files(filtered_alignments_folder,
                      output_folder,
                      batch_size=args.batch_size,
                      algorithm_suffix=algorithm_suffix,
                      logger=logger)

    # Write a report of pre-and-post filtering stats for each tree/alignments:
    write_fasta_from_tree_report(alignment_filtering_dict,
                                 args.treefile_directory,
                                 args.from_cut_deep_paralogs,
                                 algorithm_suffix,
                                 logger=logger)

    logger.info(f'{"[INFO]:":10} Finished extracting fasta sequences corresponding to tree tips.')