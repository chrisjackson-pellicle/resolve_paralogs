#!/usr/bin/env python

# Adapted from Yang and Smith by Chris Jackson chris.jackson@rbg.vic.gov.au

"""
- Cut internal branches longer than a specified length, and output subtrees as .subtree files
- If uncut and nothing changed between .treefile and .subtree, copy the original .tree file to the output directory
"""

import os
import sys
import textwrap
from collections import defaultdict
import glob
import newick3
import phylo3

from tree_utils import get_front_names, remove_kink, get_front_labels

from yang_and_smith import utils


def count_taxa(node):
    """
    Given a node, count how many taxa it has in front. Only unique taxon names are counted (i.e. all paralogs for a
    given taxon count as one).

    :param phylo3.Node node: tree object parsed by newick3.parse
    :return:
    """

    return len(set(get_front_names(node)))


def cut_long_internal_branches(curroot,
                               internal_branch_length_cutoff,
                               logger=None):
    """
    Cut long branches and output all subtrees with at least 4 tips

    :param phylo3.Node curroot: tree object parsed by newick3.parse
    :param float internal_branch_length_cutoff: internal branches >= the length will be cut
    :param logging.Logger logger: a logger object
    :return:
    """

    going = True
    subtrees = []  # store all subtrees after cutting
    subtrees_discarded = {}
    while going:
        going = False  # only keep going if long branches were found during last round
        for node in curroot.iternodes():  # Walk through nodes
            if node.istip or node == curroot:
                continue  # skip tips and root node
            if node.nchildren == 1:
                node, curroot = remove_kink(node, curroot)
                going = True
                break

            # Get child node of current node:
            child0_node, child1_node = node.children[0], node.children[1]

            if node.length > internal_branch_length_cutoff:
                logger.debug(f'{"[INFO]:":10} Internal node of length {node.length} with {len(get_front_labels(node))} '
                             f'tips is longer than the cut-off value of {internal_branch_length_cutoff}...')

                if not child0_node.istip and not child1_node.istip and \
                        child0_node.length + child1_node.length > internal_branch_length_cutoff:  # CJJ check this

                    logger.debug(f'Both child nodes are not tips and the combined length of both child node branches '
                                 f'is greater than the internal_branch_length_cutoff. child0_node.length + '
                                 f'child1_node.length is: {child0_node.length + child1_node.length}')

                    if count_taxa(child0_node) >= 4:
                        subtrees.append(child0_node)
                    else:
                        subtrees_discarded[newick3.tostring(child0_node)] = \
                            f'Node length ({node.length}) > cutoff ({internal_branch_length_cutoff}); both ' \
                            f'children not tips; combined length of child0_node branch ({child0_node.length}) and ' \
                            f'child1_node branch ({child0_node.length}) > cutoff; child0_node has fewer than 4 taxa'

                        logger.debug(f'Discarding child0_node subtree {newick3.tostring(child0_node)} as it has fewer '
                                     f'than 4 taxa')

                    if count_taxa(child1_node) >= 4:
                        subtrees.append(child1_node)
                    else:
                        subtrees_discarded[newick3.tostring(child1_node)] = \
                            f'Node length ({node.length}) > cutoff ({internal_branch_length_cutoff}); both ' \
                            f'children not tips; combined length of child0_node branch ({child0_node.length}) and ' \
                            f'child1_node branch ({child0_node.length}) > cutoff; child1_node has fewer than 4 taxa'

                        logger.debug(f'Discarding child1_node subtree {newick3.tostring(child1_node)} as it has fewer '
                                     f'than 4 taxa')

                else:  # recover entire child clade of node as a subtree
                    logger.debug(f'Internal node of length {node.length} with {len(get_front_labels(node))} tips '
                                 f'recovered as subtree.')

                    subtrees.append(node)

                node = node.prune()  # prune off node from curroot tree

                if len(curroot.leaves()) > 2:  # no kink if only two left
                    node, curroot = remove_kink(node, curroot)
                    going = True
                break

    if count_taxa(curroot) >= 4:
        subtrees.append(curroot)  # write out the residue after cutting
    else:
        subtrees_discarded[newick3.tostring(curroot)] = 'After cutting, remaining tree has fewer than 4 taxa'
        logger.debug(f'After cutting, remaining tree has fewer than 4 taxa')

    return subtrees, subtrees_discarded


def write_cut_report(collated_subtree_data,
                     treefile_directory,
                     logger=None):
    """
    Writes a *.tsv report detailing which retained subtree count, and which subtrees were discarded.

    :param dict collated_subtree_data: dictionary of default dicts for retained and discarded subtrees
    :param str treefile_directory: name of tree file directory for report filename
    :param logging.Logger logger: a logger object
    :return:
    """

    basename = os.path.basename(treefile_directory)
    report_filename = f'{basename}_cut_report.tsv'

    logger.info(f'{"[INFO]:":10} Writing cut internal branches report to file {report_filename}')

    with open(report_filename, 'w') as report_handle:

        # Write basic stats i.e. number of subtrees of various categories:
        report_handle.write(f'Tree_name\t'
                            f'Num subtrees retained after cutting\t'
                            f'Num subtrees discarded after cutting\t'
                            f'Number of subtrees discarded after cutting as < min taxa\n')
        for input_tree, dictionaries in collated_subtree_data.items():

            subtrees_dict = dictionaries['subtrees']
            subtrees_discarded_during_cutting_dict = dictionaries['subtrees_discarded_during_cutting']
            subtrees_discarded_min_taxa_filtering_dict = dictionaries['subtrees_discarded_min_taxa_filtering']

            report_handle.write(f'{input_tree}\t'
                                f'{len(subtrees_dict)}\t'
                                f'{len(subtrees_discarded_during_cutting_dict)}\t'
                                f'{len(subtrees_discarded_min_taxa_filtering_dict)}\n')

        report_handle.write(f'\t\t\t\n')

        # Write more detailed stats for discarded subtrees:
        report_handle.write(f'Tree_name\t'
                            f'Subtree discarded after cutting\t'
                            f'Reason\t\n')

        for input_tree, dictionaries in collated_subtree_data.items():

            subtrees_dict = dictionaries['subtrees']
            subtrees_discarded_during_cutting_dict = dictionaries['subtrees_discarded_during_cutting']
            subtrees_discarded_min_taxa_filtering_dict = dictionaries['subtrees_discarded_min_taxa_filtering']

            for subtree_newick_string, reason in subtrees_discarded_during_cutting_dict.items():
                report_handle.write(f'{input_tree}\t'
                                    f'{subtree_newick_string}\t'
                                    f'{reason}\t\n')

            for subtree_newick_string, reason in subtrees_discarded_min_taxa_filtering_dict.items():
                report_handle.write(f'{input_tree}\t'
                                    f'{subtree_newick_string}\t'
                                    f'{reason}\t\n')


def main(args):
    """
    Entry point for the resolve_paralogs.py script

    :param args: argparse namespace with subparser options for function main()
    :return:
    """

    # Initialise logger:
    logger = utils.setup_logger(__name__, 'logs_resolve_paralogs/06_cut_deep_paralogs')

    # check for external dependencies:
    if utils.check_dependencies(logger=logger):
        logger.info(f'{"[INFO]:":10} All external dependencies found!')
    else:
        logger.error(f'{"[ERROR]:":10} One or more dependencies not found!')
        sys.exit(1)

    logger.info(f'{"[INFO]:":10} Subcommand cut_deep_paralogs was called with these arguments:')
    fill = textwrap.fill(' '.join(sys.argv[1:]), width=90, initial_indent=' ' * 11, subsequent_indent=' ' * 11,
                         break_on_hyphens=False)
    logger.info(f'{fill}\n')

    # Create output folder:
    treefile_directory_basename = os.path.basename(args.treefile_directory)
    output_folder = f'{treefile_directory_basename}_cut'
    utils.createfolder(output_folder)
    filecount = 0

    logger.info(f'{"[INFO]:":10} Cutting internal branches longer than {args.internal_branch_length_cutoff}')

    collated_subtree_data = defaultdict(lambda: defaultdict())

    for tree_file in glob.glob(f'{args.treefile_directory}/*{args.tree_file_suffix}'):
        tree_file_basename = os.path.basename(tree_file)
        with open(tree_file, 'r') as tree_file_handle:
            intree = newick3.parse(tree_file_handle.readline())
        filecount += 1

        logger.info(f'{"[INFO]:":10} Analysing tree: {tree_file_basename}')

        raw_tree_size = len(get_front_labels(intree))  # includes paralogs
        num_taxa = count_taxa(intree)  # Unique taxon names only

        if num_taxa < args.minimum_number_taxa:
            logger.warning(f'{"[WARNING]:":10} Tree {tree_file_basename} has {num_taxa} unique taxon name, '
                           f'less than the minimum number of {args.minimum_number_taxa} specified. Skipping tree...')
        else:
            logger.info(f'{"[INFO]:":10} Tree {tree_file_basename} has {raw_tree_size} tips and {num_taxa} unique '
                        f'taxon names...')

            # Cut long internal branches if present:
            subtrees, subtrees_discarded_during_cutting = \
                cut_long_internal_branches(intree,
                                           args.internal_branch_length_cutoff,
                                           logger=logger)

            # Capture data for each tree in dictionary for report writing:
            collated_subtree_data[tree_file_basename]['subtrees'] = subtrees
            collated_subtree_data[tree_file_basename]['subtrees_discarded_during_cutting'] = \
                subtrees_discarded_during_cutting

            if len(subtrees) == 0:
                logger.warning(f'{"[WARNING]:":10} No tree with at least {args.minimum_number_taxa} was generated')

            else:
                count = 0
                subtree_sizes = []
                subtrees_discarded_min_taxa_filtering = {}

                for subtree in subtrees:
                    if count_taxa(subtree) >= args.minimum_number_taxa:
                        count += 1

                        if subtree.nchildren == 2:  # fix bifurcating roots from cutting
                            temp, subtree = remove_kink(subtree, subtree)

                        output_subtree_filename = f'{output_folder}/' \
                                                  f'{tree_file_basename.split(".")[0]}_{str(count)}.subtree'

                        with open(output_subtree_filename, 'w') as subtree_handle:
                            subtree_handle.write(newick3.tostring(subtree) + ";\n")

                        subtree_sizes.append(str(len(subtree.leaves())))
                    else:
                        logger.debug(f'Post cut filtering: subtree {newick3.tostring(subtree)} discarded as fewer '
                                     f'than minimum_number_taxa value of {args.minimum_number_taxa}')

                        subtrees_discarded_min_taxa_filtering[newick3.tostring(subtree)] = \
                            f'Post cut filtering: subtree discarded as fewer than minimum_number_taxa value of' \
                            f' {args.minimum_number_taxa}'

                # Capture data for each tree in dictionary for report writing:
                collated_subtree_data[tree_file_basename]['subtrees_discarded_min_taxa_filtering'] = \
                    subtrees_discarded_min_taxa_filtering

                subtree_sizes_joined = ', '.join(subtree_sizes)

                logger.info(f'{"[INFO]:":10} For input tree {tree_file_basename}, {count} subtree(s) were written. '
                            f'Sizes (tip numbers) were: {subtree_sizes_joined}')

    # Write a report of tips trimmed from each tree, and why:
    write_cut_report(collated_subtree_data,
                     args.treefile_directory,
                     logger=logger)

    assert filecount > 0, logger.error(f'{"[ERROR]:":10} No files with suffix {args.tree_file_suffix} found in'
                                       f' {args.treefile_directory}')






