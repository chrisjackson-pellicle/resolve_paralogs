#!/usr/bin/env python

# Author: Yang and Smith, modified by Alexander Schmidt-Lebuhn

# Modified by: Chris Jackson chris.jackson@rbg.vic.gov.au

"""
Taxon duplication? --No--> output one-to-one orthologs
        |
       Yes
        |
Outgroup present? --No--> ignore this homolog
        |
       Yes
        |
Outgroup taxon duplication? --Yes--> ignore this homolog
        |
        No
        |
Outgroup monophyletic? --No--> ignore this homolog
        |
       Yes
        |
Infer orthologs by using monophyletic, non-repeating outgroups

If not to output 1-to-1 orthologs, for example, already analysed these
set OUTPUT_1to1_ORTHOLOGS to False
"""

import phylo3
import newick3
import os
import sys
from collections import defaultdict
import glob
import shutil
import textwrap

from yang_and_smith import utils


def get_name(label):
    """
    Given a tip label, return taxon name identifier (first field after splitting by dor/period)

    :param str label: label of a tree tip
    :return:
    """

    return label.split(".")[0]


def get_cluster_id(filename):
    """
    Returns first field of tree file name, after splitting by dot/period.

    :param str filename: file name of input tree file
    :return str: first field of tree file name, after splitting by dot/period.
    """

    return filename.split(".")[0]


def get_front_labels(node):
    """

    :param phylo3.Node node: tree object parsed by newick3.parse
    :return list:
    """

    leaves = node.leaves()
    return [i.label for i in leaves]


def get_back_labels(node, root):
    """
    Return taxon names for all child tips OTH THAN the child tips of the given node

    :param phylo3.Node node: tree object parsed by newick3.parse
    :param phylo3.Node root: tree object parsed by newick3.parse
    :return set:
    """

    all_labels = get_front_labels(root)
    front_labels = get_front_labels(node)
    return set(all_labels) - set(front_labels)  # labels do not repeat


def get_front_names(node):  # may include duplicates
    """
    Return taxon names for all child tips of the given node

    :param phylo3.Node node: tree object parsed by newick3.parse
    :return list:
    """

    labels = get_front_labels(node)
    return [get_name(i) for i in labels]


def get_front_outgroup_names(node, outgroups):
    """
    Recovers taxon names in tree, and returns a list of the names that are also present in the outgroups list.

    :param phylo3.Node node: tree object parsed by newick3.parse
    :param list outgroups: list of outgroup names recovered from in_and_outgroup_list file
    :return list: a list of taxon names in the provided tree, if they are present in the outgroups list
    """

    names = get_front_names(node)
    return [i for i in names if i in outgroups]


def get_back_names(node, root):  # may include duplicates
    """

    :param phylo3.Node node: tree object parsed by newick3.parse
    :param phylo3.Node root: tree object parsed by newick3.parse
    :return list:
    """

    back_labels = get_back_labels(node, root)
    return [get_name(i) for i in back_labels]


def remove_kink(node, curroot):
    """

    :param phylo3.Node node: tree object parsed by newick3.parse
    :param phylo3.Node curroot: tree object parsed by newick3.parse
    :return:
    """

    if node == curroot and curroot.nchildren == 2:
        # move the root away to an adjacent none-tip
        if curroot.children[0].istip:  # the other child is not tip
            curroot = phylo3.reroot(curroot, curroot.children[1])
        else:
            curroot = phylo3.reroot(curroot, curroot.children[0])
    # ---node---< all nodes should have one child only now
    length = node.length + (node.children[0]).length
    par = node.parent
    kink = node
    node = node.children[0]
    # parent--kink---node<
    par.remove_child(kink)
    par.add_child(node)
    node.length = length
    return node, curroot


def reroot_with_monophyletic_outgroups(root,
                                       outgroups,
                                       logger=None):
    """
    Check if outgroups are monophyletic and non-repeating and reroot, otherwise return None

    :param phylo3.Node root: tree object parsed by newick3.parse
    :param list outgroups: a list of outgroup taxon names present in the tree
    :param logging.Logger logger: a logger object
    :return:
    """

    leaves = root.leaves()
    outgroup_matches = {}  # Key is label, value is the tip node object

    # Since no taxon repeat in outgroups name and leaf is one-to-one  # CJJ what the latter clause mean?
    outgroup_labels = []
    for leaf in leaves:
        label = leaf.label  # e.g. 376678.main or 376728.0, etc
        name = get_name(label)  # e.g. 376678 or 376728, etc
        if name in outgroups:
            outgroup_matches[label] = leaf
            outgroup_labels.append(label)

    if len(outgroup_labels) == 1:  # Tree contains a single outgroup sequence
        # cannot reroot on a tip so have to go one more node into the ingroup:
        new_root = outgroup_matches[outgroup_labels[0]].parent
        return phylo3.reroot(root, new_root)

    else:  # Tree has multiple outgroup sequences. Check monophyly and reroot:
        newroot = None
        for node in root.iternodes():  # Iterate over nodes and try to find one with monophyletic outgroup
            if node == root:
                continue  # Skip the root

            front_names = get_front_names(node)
            back_names = get_back_names(node, root)
            front_in_names, front_out_names, back_in_names, back_out_names = 0, 0, 0, 0

            # Get counts of ingroup and outgroup taxa at front and back of the current node:
            for i in front_names:
                if i in outgroups:
                    front_out_names += 1
                else:
                    front_in_names += 1
            for j in back_names:
                if j in outgroups:
                    back_out_names += 1
                else:
                    back_in_names += 1

            if front_in_names == 0 and front_out_names > 0 and back_in_names > 0 and back_out_names == 0:
                newroot = node.parent  # ingroup at back, outgroup in front CJJ added.parent - bugfix?
                break

            if front_in_names > 0 and front_out_names == 0 and back_in_names == 0 and back_out_names > 0:
                newroot = node.parent  # ingroup in front, outgroup at back
                break

        if newroot:
            return phylo3.reroot(root, newroot)
        else:
            return None


def prune_paralogs_from_rerooted_homotree(root,
                                          outgroups,
                                          logger=None):
    """
    Prunes a tree containing monophletic outgroup sequences to recover the ingroup clade with the largest number of
    non-repeating taxon names. Returned tree contains outgroup sequences.

    :param phylo3.Node root: tree object parsed by newick3.parse
    :param list outgroups: list of outgroup names recovered from in_and_outgroup_list file
    :param logging.Logger logger: a logger object
    :return phylo3.Node root: tree object after pruning with Monophyletic Outgroups (MO) algorithm
    """

    if len(get_front_names(root)) == len(set(get_front_names(root))):
        return root  # no pruning needed CJJ This is same as 1to1_orthologs, isn't it?

    # Check for duplications at the root first. One or two of the trifurcating root clades are ingroup clades:
    node0, node1, node2 = root.children[0], root.children[1], root.children[2]
    out0, out1, out2 = len(get_front_outgroup_names(node0, outgroups)),\
                       len(get_front_outgroup_names(node1, outgroups)),\
                       len(get_front_outgroup_names(node2, outgroups))

    logger.debug(f'Outgroup taxon count in node0, node1, node2 is: {out0}, {out1}, {out2}')

    # Identify the ingroup clades and check for names overlap:
    if out0 == 0 and out1 == 0:  # 0 and 1 are the ingroup clades
        name_set0 = set(get_front_names(node0))
        name_set1 = set(get_front_names(node1))
        if len(name_set0.intersection(name_set1)) > 0:

            if len(name_set0) > len(name_set1):  # cut the side with fewer taxa
                logger.debug(f'Cutting node1: {newick3.tostring(node1)}')
                root.remove_child(node1)
                node1.prune()
            else:
                root.remove_child(node0)  # CJJ arbitrary removal of node0 rather than node1 if same number taxa?
                logger.debug(f'Cutting node0: {newick3.tostring(node0)}')
                node0.prune()

    elif out1 == 0 and out2 == 0:  # 1 and 2 are the ingroup clades
        name_set1 = set(get_front_names(node1))
        name_set2 = set(get_front_names(node2))
        if len(name_set1.intersection(name_set2)) > 0:
            if len(name_set1) > len(name_set2):  # cut the side with fewer taxa
                logger.debug(f'Cutting node2: {newick3.tostring(node2)}')
                root.remove_child(node2)
                node2.prune()
            else:
                root.remove_child(node1)
                logger.debug(f'Cutting node1: {newick3.tostring(node1)}')
                node1.prune()

    elif out0 == 0 and out2 == 0:  # 0 and 2 are the ingroup clades
        name_set0 = set(get_front_names(node0))
        name_set2 = set(get_front_names(node2))
        if len(name_set0.intersection(name_set2)) > 0:
            if len(name_set0) > len(name_set2):  # cut the side with fewer taxa
                root.remove_child(node2)
                logger.debug(f'Cutting node2: {newick3.tostring(node2)}')
                node2.prune()
            else:
                root.remove_child(node0)
                logger.debug(f'Cutting node0: {newick3.tostring(node0)}')
                node0.prune()

    else:
        raise ValueError('More than one clade with outgroup sequences!')

    # If there are still taxon duplications (putative paralogs) in the ingroup clade, keep pruning:
    while len(get_front_names(root)) > len(set(get_front_names(root))):
        for node in root.iternodes(order=0):  # PREORDER, root to tip  CJJ: this tree includes outgroup taxa

            if node.istip:
                continue
            elif node == root:
                continue

            child0, child1 = node.children[0], node.children[1]
            name_set0 = set(get_front_names(child0))
            name_set1 = set(get_front_names(child1))
            if len(name_set0.intersection(name_set1)) > 0:
                if len(name_set0) > len(name_set1):  # cut the side with fewer taxa
                    node.remove_child(child1)
                    child1.prune()
                else:
                    node.remove_child(child0)
                    child0.prune()
                node, root = remove_kink(node, root)  # no re-rooting here
                break

    return root


def parse_ingroup_and_outgroup_file(in_out_file, logger=None):
    """

    :param str in_out_file: path to the text file containing ingroup and outgroup designations
    :param logging.Logger logger: a logger object
    :return list ingroups, outgroups: lists of ingroup taxa and outgroup taxa
    """

    ingroups = []
    outgroups = []

    with open(in_out_file, 'r') as in_out_handle:
        for line in in_out_handle:
            if len(line) < 3:
                logger.debug(f'Skipping line {line} in in_out_file {os.path.basename(in_out_file)} as len < 3')
                continue
            sample = line.strip().split("\t")
            if sample[0] == "IN":
                ingroups.append(sample[1])
            elif sample[0] == "OUT":
                outgroups.append(sample[1])
            else:
                logger.error(f'{"[ERROR]:":10} Check in_and_outgroup_list file format for the following line:')
                logger.error(f'\n{" " * 10} {line}')
                sys.exit(1)

    # Check if there are taxa designated as both ingroup AND outgroup:
    if len(set(ingroups) & set(outgroups)) > 0:
        logger.error(f'{"[ERROR]:":10} Taxon ID {set(ingroups)} & {set(outgroups)} are in both ingroup and outgroup!')
        sys.exit(1)

    logger.info(f'{"[INFO]:":10} There are {len(ingroups)} ingroup taxa and {len(outgroups)} outgroup taxa on the'
                f' {os.path.basename(in_out_file)} file provided')

    return ingroups, outgroups


def write_mo_report(treefile_directory,
                    trees_with_fewer_than_minimum_taxa,
                    trees_with_1to1_orthologs,
                    trees_with_no_outgroup_taxa,
                    trees_with_unrecognised_taxon_names,
                    tree_with_duplicate_taxa_in_outgroup,
                    trees_with_monophyletic_outgroups,
                    trees_with_non_monophyletic_outgroups,
                    trees_with_mo_output_file_above_minimum_taxa,
                    trees_with_mo_output_file_below_minimum_taxa,
                    logger=None):
    """
    Writes a *.tsv report detailing for Monophyletic Ourgroup pruning process.

    :param str treefile_directory: name of tree file directory for report filename
    :param trees_with_fewer_than_minimum_taxa: dictionary of treename:newick
    :param trees_with_1to1_orthologs: dictionary of treename:newick
    :param trees_with_no_outgroup_taxa: dictionary of treename:newick
    :param trees_with_unrecognised_taxon_names: dictionary of treename: list of unrecognised taxa
    :param tree_with_duplicate_taxa_in_outgroup: dictionary of treename:newick
    :param trees_with_monophyletic_outgroups: dictionary of treename:newick
    :param trees_with_non_monophyletic_outgroups: dictionary of treename:newick
    :param trees_with_mo_output_file_above_minimum_taxa: dictionary of treename:newick
    :param trees_with_mo_output_file_below_minimum_taxa: dictionary of treename:newick
    :param logging.Logger logger: a logger object
    :return:
    """

    basename = os.path.basename(treefile_directory)
    report_filename = f'{basename}_MO_report.tsv'

    logger.info(f'{"[INFO]:":10} Writing Monophyletic Outgroup (MO) report to file {report_filename}')

    with open(report_filename, 'w') as report_handle:
        report_handle.write(f'\t'
                            f'Input trees with unrecognised taxa (skipped)\t'
                            f'Input trees with fewer than minimum taxa (skipped)\t'
                            f'Input trees with 1-to-1 orthologs\t'
                            f'Input trees with no outgroup taxa\t'
                            f'Input trees with duplicate taxa in the outgroup\t'
                            f'Input trees with putative paralogs and monophyletic outgroup\t'
                            f'Input trees with putative paralogs and non-monophyletic outgroup\t'
                            f'MO pruned trees with greater than minimum taxa\t'
                            f'MO pruned trees with fewer than minimum taxa'
                            f'\n')

        report_handle.write(f'Number of trees\t'
                            f'{len(trees_with_unrecognised_taxon_names)}\t'
                            f'{len(trees_with_fewer_than_minimum_taxa)}\t'
                            f'{len(trees_with_1to1_orthologs)}\t'
                            f'{len(trees_with_no_outgroup_taxa)}\t'
                            f'{len(tree_with_duplicate_taxa_in_outgroup)}\t'
                            f'{len(trees_with_monophyletic_outgroups)}\t'
                            f'{len(trees_with_non_monophyletic_outgroups)}\t'
                            f'{len(trees_with_mo_output_file_above_minimum_taxa)}\t'
                            f'{len(trees_with_mo_output_file_below_minimum_taxa)}'
                            f'\n')

        if trees_with_unrecognised_taxon_names:
            tree_names_with_unrecognised_taxon_names = ''
            for treename, unrecognised_taxon_names_list in trees_with_unrecognised_taxon_names.items():
                unrecognised_taxon_names_joined = ', '.join(unrecognised_taxon_names_list)
                tree_names_with_unrecognised_taxon_names = f'{tree_names_with_unrecognised_taxon_names} {treename}:' \
                                                           f' {unrecognised_taxon_names_joined}, '
        else:
            tree_names_with_unrecognised_taxon_names = 'None'

        if trees_with_fewer_than_minimum_taxa:
            tree_names_minimum_taxa_joined = ', '.join(trees_with_fewer_than_minimum_taxa.keys())
        else:
            tree_names_minimum_taxa_joined = 'None'

        if trees_with_1to1_orthologs:
            tree_names_1to1_orthologs_joined = ', '.join(trees_with_1to1_orthologs.keys())
        else:
            tree_names_1to1_orthologs_joined = 'None'

        if trees_with_no_outgroup_taxa:
            tree_names_with_no_outgroup_taxa_joined = ', '.join(trees_with_no_outgroup_taxa.keys())
        else:
            tree_names_with_no_outgroup_taxa_joined = 'None'

        if tree_with_duplicate_taxa_in_outgroup:
            tree_names_with_duplicate_taxa_in_outgroup_joined = ', '.join(tree_with_duplicate_taxa_in_outgroup.keys())
        else:
            tree_names_with_duplicate_taxa_in_outgroup_joined = 'None'

        if trees_with_monophyletic_outgroups:
            tree_names_with_monophyletic_outgroups_joined = ', '.join(trees_with_monophyletic_outgroups.keys())
        else:
            tree_names_with_monophyletic_outgroups_joined = 'None'

        if trees_with_non_monophyletic_outgroups:
            tree_names_with_non_monophyletic_outgroups_joined = ', '.join(trees_with_non_monophyletic_outgroups.keys())
        else:
            tree_names_with_non_monophyletic_outgroups_joined = 'None'

        if trees_with_mo_output_file_above_minimum_taxa:
            tree_names_with_mo_output_file_above_minimum_taxa_joined = \
                ', '.join(trees_with_mo_output_file_above_minimum_taxa.keys())
        else:
            tree_names_with_mo_output_file_above_minimum_taxa_joined = 'None'

        if trees_with_mo_output_file_below_minimum_taxa:
            tree_names_with_mo_output_file_below_minimum_taxa_joined = \
                ', '.join(trees_with_mo_output_file_below_minimum_taxa.keys())
        else:
            tree_names_with_mo_output_file_below_minimum_taxa_joined = 'None'

        report_handle.write(f'Tree names\t'
                            f'{tree_names_with_unrecognised_taxon_names}\t'
                            f'{tree_names_minimum_taxa_joined}\t'
                            f'{tree_names_1to1_orthologs_joined}\t'
                            f'{tree_names_with_no_outgroup_taxa_joined}\t'
                            f'{tree_names_with_duplicate_taxa_in_outgroup_joined}\t'
                            f'{tree_names_with_monophyletic_outgroups_joined}\t'
                            f'{tree_names_with_non_monophyletic_outgroups_joined}\t'
                            f'{tree_names_with_mo_output_file_above_minimum_taxa_joined}\t'
                            f'{tree_names_with_mo_output_file_below_minimum_taxa_joined}\t'
                            f'\n')

def main(args):
    """
    Entry point for the resolve_paralogs.py script

    :param args: argparse namespace with subparser options for function main()
    :return:
    """

    # Initialise logger:
    logger = utils.setup_logger(__name__, 'logs_resolve_paralogs/09_prune_paralogs_MO')

    # check for external dependencies:
    if utils.check_dependencies(logger=logger):
        logger.info(f'{"[INFO]:":10} All external dependencies found!')
    else:
        logger.error(f'{"[ERROR]:":10} One or more dependencies not found!')
        sys.exit(1)

    logger.info(f'{"[INFO]:":10} Subcommand prune_paralogs_MO was called with these arguments:')
    fill = textwrap.fill(' '.join(sys.argv[1:]), width=90, initial_indent=' ' * 11, subsequent_indent=' ' * 11,
                         break_on_hyphens=False)
    logger.info(f'{fill}\n')
    logger.debug(args)

    # Create output folder for pruned trees:
    output_folder = f'{os.path.basename(args.treefile_directory)}_pruned_MO'
    utils.createfolder(output_folder)

    # Parse the ingroup and outgroup text file:
    ingroups, outgroups = parse_ingroup_and_outgroup_file(args.in_and_outgroup_list,
                                                          logger=logger)

    # Create dicts for report file:
    trees_with_fewer_than_minimum_taxa = {}
    trees_with_1to1_orthologs = {}
    trees_with_no_outgroup_taxa = {}
    trees_with_unrecognised_taxon_names = defaultdict(list)
    tree_with_duplicate_taxa_in_outgroup = {}
    trees_with_monophyletic_outgroups = {}
    trees_with_non_monophyletic_outgroups = {}
    trees_with_mo_output_file_above_minimum_taxa = {}
    trees_with_mo_output_file_below_minimum_taxa = {}

    # Iterate over tree and prune with MO algorithm:
    for treefile in glob.glob(f'{args.treefile_directory}/*{args.tree_file_suffix}'):
        treefile_basename = os.path.basename(treefile)
        outout_file_id = f'{output_folder}/{get_cluster_id(treefile_basename)}'

        logger.info(f'{"[INFO]:":10} Analysing tree {treefile_basename}...')

        # Read in the tree and check number of taxa:
        with open(treefile, "r") as infile:
            intree = newick3.parse(infile.readline())
            curroot = intree
            names = get_front_names(curroot)
            num_tips, num_taxa = len(names), len(set(names))

            # Check for unrecognised tip names and skip tree if present:
            unrecognised_names = False
            for name in names:
                if name not in ingroups and name not in outgroups:
                    logger.warning(f'{"[WARNING]:":10} Taxon name {name} in tree {treefile_basename} not found in '
                                   f'ingroups or outgroups. Skipping tree...')
                    trees_with_unrecognised_taxon_names[treefile_basename].append(name)
                    unrecognised_names = True
            if unrecognised_names:
                continue

            # Check if tree contains more than the minimum number of taxa:
            if num_taxa < args.minimum_taxa:
                logger.warning(f'{"[WARNING]:":10} Tree {treefile_basename} contains {num_taxa} taxa; minimum_taxa '
                               f'required is {args.minimum_taxa}. Skipping tree...')

                trees_with_fewer_than_minimum_taxa[treefile_basename] = newick3.tostring(curroot)

                continue  # Not enough taxa, skip tree

        # If the tree has no taxon duplication, no cutting is needed:
        if num_tips == num_taxa:
            logger.info(f'{"[INFO]:":10} Tree {treefile_basename} contain no duplicated taxon names (i.e. paralogs).')

            trees_with_1to1_orthologs[treefile_basename] = newick3.tostring(curroot)

            if not args.ignore_1to1_orthologs:
                logger.info(f'{"[INFO]:":10} Writing tree {treefile_basename} to {outout_file_id}.1to1ortho.tre')
                shutil.copy(treefile, f'{outout_file_id}.1to1ortho.tre')
            else:
                logger.info(f'{"[INFO]:":10} Parameter --ignore_1to1_orthologs provided: skipping tree'
                            f' {treefile_basename}')
        else:
            # Now need to deal with taxon duplications. Check to make sure that the ingroup and outgroup names were
            # set correctly:
            logger.info(f'{"[INFO]:":10} Tree {treefile_basename} contains paralogs...')

            outgroup_names = get_front_outgroup_names(curroot, outgroups)

            # If no outgroup at all, do not attempt to resolve paralogs:
            if len(outgroup_names) == 0:
                logger.info(f'{"[WARNING]:":10} Tree {treefile_basename} contains no outgroup taxa. Skipping tree...')
                trees_with_no_outgroup_taxa[treefile_basename] = newick3.tostring(curroot)

            # Skip the tree if there are duplicated outgroup taxa
            elif len(outgroup_names) > len(set(outgroup_names)):
                logger.info(f'{"[WARNING]:":10} Tree {treefile_basename} contains duplicate taxon names in the  '
                            f'outgroup taxa. Skipping tree...')
                tree_with_duplicate_taxa_in_outgroup[treefile_basename] = newick3.tostring(curroot)

            else:  # At least one outgroup present and there's no outgroup duplication
                if curroot.nchildren == 2:  # need to reroot
                    temp, curroot = remove_kink(curroot, curroot)

                # Check if the outgroup sequenes are monophyletic:
                curroot = reroot_with_monophyletic_outgroups(curroot,
                                                             outgroups,
                                                             logger=logger)

                # Only return one tree after pruning:
                if curroot:  # i.e. the outgroup was monophyletic
                    logger.info(f'{"[INFO]:":10} Outgroup sequences are monophletic for tree {treefile_basename}.')
                    trees_with_monophyletic_outgroups[treefile_basename] = newick3.tostring(curroot)

                    # Write re-rooted trees with monophyletic outgroup to file:
                    with open(f'{outout_file_id}.reroot', "w") as outfile:
                        outfile.write(newick3.tostring(curroot) + ";\n")

                    # Prune the re-rooted tree with the MO algorith:
                    logger.info(f'{"[INFO]:":10} Applying Monophyletic Outgroup algorithm to tree {treefile_basename}...')
                    ortho = prune_paralogs_from_rerooted_homotree(curroot,
                                                                  outgroups,
                                                                  logger=logger)

                    # Filter out pruned trees that have fewer than the minimum_taxa value:
                    # CJJ the filter below counts outgroup taxa - surely just want to count ingroup taxa?
                    if len(set(get_front_names(curroot))) >= args.minimum_taxa:
                        with open(f'{outout_file_id}.ortho.tre', "w") as outfile:
                            outfile.write(newick3.tostring(ortho) + ";\n")
                            trees_with_mo_output_file_above_minimum_taxa[treefile_basename] = newick3.tostring(curroot)
                    else:
                        logger.warning(f'{"[WARNING]:":10} After pruning with MO algorith, tree {treefile_basename} '
                                       f'contains {len(set(get_front_names(curroot)))} taxa; parameter --minimum_taxa is'
                                       f' {args.minimum_taxa}. No tree file will be written.')
                        trees_with_mo_output_file_below_minimum_taxa[treefile_basename] = newick3.tostring(curroot)
                else:
                    logger.info(f'{"[INFO]:":10} Outgroup non-monophyletic for tree {treefile_basename}')
                    trees_with_non_monophyletic_outgroups[treefile_basename] = newick3.tostring(curroot)

    write_mo_report(args.treefile_directory,
                    trees_with_fewer_than_minimum_taxa,
                    trees_with_1to1_orthologs,
                    trees_with_no_outgroup_taxa,
                    trees_with_unrecognised_taxon_names,
                    tree_with_duplicate_taxa_in_outgroup,
                    trees_with_monophyletic_outgroups,
                    trees_with_non_monophyletic_outgroups,
                    trees_with_mo_output_file_above_minimum_taxa,
                    trees_with_mo_output_file_below_minimum_taxa,
                    logger=logger)