# -*- coding: utf-8 -*-
# QuickFF is a code to quickly derive accurate force fields from ab initio input.
# Copyright (C) 2012 - 2015 Louis Vanduyfhuys <Louis.Vanduyfhuys@UGent.be>
# Steven Vandenbrande <Steven.Vandenbrande@UGent.be>,
# Toon Verstraelen <Toon.Verstraelen@UGent.be>, Center for Molecular Modeling
# (CMM), Ghent University, Ghent, Belgium; all rights reserved unless otherwise
# stated.
#
# This file is part of QuickFF.
#
# QuickFF is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# QuickFF is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>
#
#--

from molmod.units import deg
from molmod.ic import bond_length, dihed_angle
from yaff.sampling.harmonic import estimate_cart_hessian

import numpy as np, math

from quickff.ic import IC
from quickff.terms import HarmonicTerm, CosineTerm
from quickff.fftable import DataArray, FFTable

__all__ = [
    'Model', 'AIPart', 'EIPart', 'ValencePart', 'ZeroPot', 'HarmonicPot',
    'CoulPointPot', 'CoulGaussPot', 'LennardJonesPot', 'MM3BuckinghamPot',
    'NonbondedYaffPot', 'TermListPot',
]


class Model(object):
    '''
       A class defining the ab initio total energy of the system,
       the force field electrostatic contribution and the
       force field valence contribution.
    '''

    def __init__(self, ai, val, ei, vdw, nbyaff=None):
        '''
           **Arguments**

           ai
                A model for the ab initio total energy, should be an instance
                of AIPart

           val
                an instance of the ValencePart class containing all details
                of the force field valence terms.

           ei
                A model for the force field electrostatic energy, should be
                an instance of EIPart

           vdw
                A model for the force field van der Waals energy, should be
                an instance of VDWPart

           nbyaff
                A model for the forcefield nonbonded energy, specified with a
                Yaff Forcefield instance. Should be an instance of
                NonbondedYaffPart. If not specified, this defaults to a zero
                potential.
        '''
        self.ai = ai
        self.val = val
        self.ei = ei
        self.vdw = vdw
        # If no NonbondedYaffPart is specified, add one that defaults to a zero
        # potential.
        if nbyaff is None: nbyaff = NonbondedYaffPart()
        self.nbyaff = nbyaff

    @classmethod
    def from_system(cls, system, ai_project=True, ic_ids=['all'],
        ei_scales=[0.0,0.0,1.0], ei_pot_kind='Harmonic',
        vdw_scales=[0.0,0.0,1.0], vdw_pot_kind='Harmonic'):
        '''
            **Arguments**

            system
                An instance of the System class containing all the information
                of the system.

            **Optional Arguments**

            ai_project
                If True, project the translational and rotational degrees of
                freedom out of the hessian.

            ic_ids
                A list of identifiers specifying which icnames should be
                included in the Valence Part. Each identifier can be a specific
                IC name such as 'bond/C3_cc.H1_c' or can be one of the following
                strings: 'bonds', 'angles', 'diheds', 'opdists' or 'all'.

            ei_scales
                a list containing the scales for the 1-2, 1-3 and 1-4
                contribution to the electrostatic interactions

            ei_pot_kind
                a string defining the potential kind of the electrostatic
                interactions. Can be 'CoulPoint', 'CoulGauss', 'HarmPoint'
                'HarmGauss' or 'Zero'. If 'CoulPoint'/'CoulGauss' is chosen,
                the exact Coulombic potential between point/gaussian charges
                will be used to evaluate EI interactions. If
                'HarmPoint'/'HarmGauss' is chosen, a second order Taylor
                expansion of the Coulomb potential is used. Harmonic is a lot
                faster and should already give accurate results.

            vdw_scales
                a list containing the scales for the 1-2, 1-3 and 1-4
                contribution to the van der Waals interactions

            vdw_pot_kind
                a string defining the potential kind of the van der Waals
                interactions. Can be 'LJ', 'MM3', 'HarmLJ', 'HarmMM3' or 'Zero'.
                If LJ/MM3 is chosen, the exact Lennard-Jones/MM3-Buckingham
                potential will be used to evaluate van der Waals interactions.
                If HarmLJ/HarmMM3 is chosen, a second order Taylor expansion of
                the LJ/MM3 potential is used. Harmonic is a lot faster and
                should already give accurate results.
        '''
        ai  = AIPart.from_system(system, ai_project)
        ei  = EIPart.from_system(system, ei_scales, ei_pot_kind)
        vdw = VDWPart.from_system(system, vdw_scales, vdw_pot_kind)
        val = ValencePart.from_system(system, ic_ids=ic_ids)
        return cls(ai, val, ei, vdw)

    def print_info(self):
        '''
            Print some basic information about the model.
        '''
        self.ai.print_info()
        self.ei.print_info()
        self.vdw.print_info()
        self.nbyaff.print_info()
        self.val.print_info()


#####  PES Parts


class BasePart(object):
    '''
        A base class for several parts to the AI and FF PES
    '''
    def __init__(self, name, pot):
        self.name = name
        self.pot = pot

    def calc_energy(self, coords):
        return self.pot.calc_energy(coords)

    def calc_gradient(self, coords):
        return self.pot.calc_gradient(coords)

    def calc_hessian(self, coords):
        return self.pot.calc_hessian(coords)

    def print_info(self):
        print '    %s kind = %s' %(self.name, self.pot.kind)


class AIPart(BasePart):
    '''
        A class for describing the Ab initio PES.
    '''
    def __init__(self, pot, project=True):
        '''
            **Arguments**

            pot
                An instance of HarmonicPot defining the second order Taylor
                expansion of the ab initio energy.

            **Optional Arguments**

            project
                Boolean specifying wheter or not the translational and
                rotational degrees of freedom should be projected out of the
                ab initio Hessian [default=True].
        '''
        BasePart.__init__(self, 'AI Total', pot)
        self.project = project

    @classmethod
    def from_system(cls, system, project=True):
        '''
        Method to construct a AIPart instance from a System instance.

        **Arguments**

        system
            An instance of the System class containing all system information.
            The attributes system.ref.coords, system.ref.grad and
            system.ref.hess (or system.ref.phess in case project=True) will be
            used to construct the Taylor expansion.

        **Optional Arguments**

            project
                Boolean specifying wheter or not the translational and
                rotational degrees of freedom should be projected out of the
                ab initio Hessian [default=True].
        '''
        if project:
            hess = system.ref.phess.copy()
        else:
            hess = system.ref.hess.copy()
        pot = HarmonicPot(
            'AbInitio', system.ref.coords.copy(), 0.0,
            system.ref.grad.copy(), hess
        )
        return cls(pot, project)

    def print_info(self):
        'Method to dump basic information about the ab initio model.'
        print '    %s project Rot/Trans = ' %self.name, self.project
        BasePart.print_info(self)


class EIPart(BasePart):
    '''
        A class for describing the electrostatic part to the FF PES.
    '''
    def __init__(self, pot, scales):
        '''
            **Arguments**

            pot
                An instance of HarmonicPot, CoulPointPot or CoulGaussPot
                defining the electrostatic contribution to the force field
                energy.

            scales
                list of 3 floats specifying the scales of the electrostatic
                interactions between 1-2, 1-3 and 1-4 atom pairs.
        '''
        BasePart.__init__(self, 'FF Electrostatic', pot)
        self.scales = scales

    @classmethod
    def from_system(cls, system, scales, pot_kind):
        '''
            Method to construct a EIPart instance from a System instance. All
            necessary information will be extraced from the system instance.

            **Arguments**

            system
                An instance of the System class from which charges, radii,
                coordinates, ... will be read.

            scales
                list of 3 floats specifying the scales of the electrostatic
                interactions between 1-2, 1-3 and 1-4 atom pairs.

            pot_kind
                A string defining the electrostatic potential. Should be one of:
                Zero, HarmPoint, HarmGauss, CoulPoint or CoulGauss.
        '''
        if pot_kind.lower() == 'zero':
            pot = ZeroPot()
        else:
            #Generate list of atom pairs subject ot EI-scaling according to scales
            scaled_pairs = [[],[],[]]
            for bond in system.bonds:
                scaled_pairs[0].append([bond[0], bond[1]])
            for bend in system.bends:
                scaled_pairs[1].append([bend[0], bend[2]])
            for dihed in system.diheds:
                scaled_pairs[2].append([dihed[0], dihed[3]])
            #Construct the exact (Coulomb) potential
            if pot_kind.lower() in ['coulpoint', 'harmpoint']:
                exact = CoulPointPot(system.charges.copy(), scales, scaled_pairs, coords0=system.ref.coords.copy())
            elif pot_kind.lower() in ['coulgauss', 'harmgauss']:
                exact = CoulGaussPot(system.charges.copy(), system.radii.copy(), scales, scaled_pairs, coords0=system.ref.coords.copy())
            else:
                raise ValueError('EI potential kind not supported: %s' %pot_kind)
            #Approximate potential if necessary
            if pot_kind.lower() in ['harmpoint', 'harmgauss']:
                grad = exact.calc_gradient(system.ref.coords.copy())
                hess = exact.calc_hessian(system.ref.coords.copy())
                pot = HarmonicPot(exact.kind, system.ref.coords.copy(), 0.0, grad, hess)
            else:
                assert pot_kind.lower() in ['coulpoint', 'coulgauss'], 'InternalError: inconsistent pot_kind checks!'
                pot = exact
        return cls(pot, scales)

    def print_info(self):
        'Method to dump basic information about the electrostatic part.'
        print '    %s scales = %.2f %.2f %.2f' %(self.name, self.scales[0], self.scales[1], self.scales[2])
        BasePart.print_info(self)


class VDWPart(BasePart):
    '''
        A class for describing the van der Waals part to the FF PES.
    '''
    def __init__(self, pot, scales):
        '''
            **Arguments**

            pot
                An instance of HarmonicPot, LennardJonesPot or MM3BuckinghamPot
                defining the van der Waals contribution to the force field
                energy.

            scales
                list of 3 floats specifying the scales of the van der Waals
                interactions between 1-2, 1-3 and 1-4 atom pairs.
        '''
        BasePart.__init__(self, 'FF van der Waals', pot)
        self.scales = scales

    @classmethod
    def from_system(cls, system, scales, pot_kind):
        '''
            Method to construct a VDWPart instance from a System instance. All
            necessary information will be extraced from the system instance.

            **Arguments**

            system
                An instance of the System class from which epsilons, sigmas,
                coordinates, ... will be read.

            scales
                list of 3 floats specifying the scales of the van der Waals
                interactions between 1-2, 1-3 and 1-4 atom pairs.

            pot_kind
                A string defining the van der Waals potential. Should be one of:
                Zero, HarmLJ, HarmMM3, LJ or MM3.
        '''
        if pot_kind.lower() == 'zero':
            pot = ZeroPot()
        else:
            #Generate list of atom pairs subject ot VDW-scaling according to scales
            scaled_pairs = [[],[],[]]
            for bond in system.bonds:
                scaled_pairs[0].append([bond[0], bond[1]])
            for bend in system.bends:
                scaled_pairs[1].append([bend[0], bend[2]])
            for dihed in system.diheds:
                scaled_pairs[2].append([dihed[0], dihed[3]])
            #Construct the exact potential
            if pot_kind.lower() in ['lj', 'harmlj']:
                exact = LennardJonesPot(system.sigmas.copy(), system.epsilons.copy(), scales, scaled_pairs, coords0=system.ref.coords.copy())
            elif pot_kind.lower() in ['mm3', 'harmmm3']:
                exact = MM3BuckinghamPot(system.sigmas.copy(), system.epsilons.copy(), scales, scaled_pairs, coords0=system.ref.coords.copy())
            #Approximate potential if necessary
            if pot_kind.lower() in ['harmlj', 'harmmm3']:
                grad = exact.calc_gradient(system.ref.coords.copy())
                hess = exact.calc_hessian(system.ref.coords.copy())
                pot = HarmonicPot(exact.kind, system.ref.coords.copy(), 0.0, grad, hess)
            else:
                assert pot_kind.lower() in ['lj', 'mm3'], 'InternalError: inconsistent pot_kind checks!'
                pot = exact
        return cls(pot, scales)

    def print_info(self):
        'Method to dump basic information about the van der Waals part.'
        print '    %s scales = %.2f %.2f %.2f' %(self.name, self.scales[0], self.scales[1], self.scales[2])
        BasePart.print_info(self)


class NonbondedYaffPart(BasePart):
    '''
        A class for describing the nonbonded part of the PES with a Yaff
        Forcefield instance.
    '''
    def __init__(self, pot=None):
        if pot is None: pot = ZeroPot()
        BasePart.__init__(self, 'Nonbonded Yaff', pot)


class ValencePart(BasePart):
    '''
        A class managing all valence force field terms. This class will mainly
        be used in the second step of the fitting procedure, when the force
        constants are refined at fixed values for the rest values.
    '''
    def __init__(self, pot):
        '''
            **Arguments**

            pot
                An instance of TermListPot defining the covalent contribution
                to the force field energy.
        '''
        BasePart.__init__(self, 'FF Covalent', pot)

    @classmethod
    def from_system(cls, system, ic_ids=['all']):
        '''
            Method to construct a ValencePart instance from a System instance.
            All necessary information will be extraced from the system instance.

            **Arguments**

            system
                An instance of the System class from which internal coordinates
                will be read.
        '''
        #Determine the icnames that are to be included in the valence model
        icnames = []
        for identifier in ic_ids:
            found = False
            if identifier.lower() in ['bonds', 'dists', 'lengths', 'all']:
                found = True
                for icname in system.ics.keys():
                    if icname.startswith('bond'):
                        icnames.append(icname)
            if identifier.lower() in ['bends', 'angles', 'all']:
                found = True
                for icname in system.ics.keys():
                    if icname.startswith('angle'):
                        icnames.append(icname)
            if identifier.lower() in ['diheds', 'dihedrals', 'all']:
                found = True
                for icname in system.ics.keys():
                    if icname.startswith('dihed'):
                        icnames.append(icname)
            if identifier.lower() in ['opdists', 'oopdists', 'all']:
                found = True
                for icname in system.ics.keys():
                    if icname.startswith('opdist'):
                        icnames.append(icname)
            if not found and identifier in system.ics.keys():
                icnames.append(identifier)
            elif not found:
                raise ValueError('Invalid IC identifier %s' %identifier)
        #Construct the valence model
        vterms = {}
        for icname in sorted(icnames):
            assert type(icname)==str, 'icnames should be a list of strings'
            assert icname in system.ics.keys(), 'icname %s not found in system' %icname
            terms = []
            for ic in system.ics[icname]:
                if icname.startswith('dihed'):
                    #Dihedral potential is determined later based on the geometry
                    terms.append(None)
                else:
                    terms.append(HarmonicTerm(ic, system.ref.coords, None, None))
            vterms[icname] = terms
        pot = TermListPot(vterms)
        return cls(pot)

    def print_info(self):
        'Method to dump basic information about the covalent part.'
        BasePart.print_info(self)
        maxlength = min(max([len(icname) for icname in self.pot.terms.keys()]) + 4, 35)
        lines = '    '
        for i, icname in enumerate(sorted(self.pot.terms.keys())):
            lines += '    %s' %( icname + ' '*(maxlength-len(icname)) )
            if (i+1)%4==0:
                lines += '\n    '
        lines.rstrip('\n    ')
        print '    %s term icnames:' %self.name
        print ''
        print lines

    def determine_dihedral_potentials(self, system, marge2=15*deg, marge3=15*deg, verbose=True):
        '''
            Determine the potential of every dihedral based on the values of
            the dihedral angles in the geometry. First try if a cosine potential
            of the form 0.5*K*[1 - cos(m(psi-psi0))] works well with m=2,3 and
            psi0 = 0,pi/m. If this doesn't work, raise a warning and ignore
            dihedral.
        '''
        maxlength = max([len(icname) for icname in system.ics.keys()]) + 2
        deleted_diheds = []
        def determine_mrv(m, psi):
            per = 360*deg/m
            val = psi%per
            if (val>=0 and val<=per/6.0) or (val>=5*per/6.0 and val<=per):
                return m, 0.0
            elif val>=2*per/6.0 and val<=4*per/6.0:
                return m, per/2.0
            else:
                return -1, 0.0
        for icname in sorted(self.pot.terms.keys()):
            if not icname.startswith('dihed'):
                continue
            ms = []
            rvs = []
            descr = icname + ' '*(maxlength-len(icname))
            ics = system.ics[icname]
            for ic in ics:
                psi0 = abs(ic.value(system.ref.coords))
                n1 = len(system.nlist[ic.indexes[1]])
                n2 = len(system.nlist[ic.indexes[2]])
                if set([n1,n2])==set([4,4]):
                    m, rv = determine_mrv(3, psi0)
                elif set([n1,n2])==set([3,4]):
                    m, rv = determine_mrv(6, psi0)
                elif set([n1,n2])==set([2,4]):
                    m, rv = determine_mrv(3, psi0)
                elif set([n1,n2])==set([3,3]):
                    m, rv = determine_mrv(2, psi0)
                elif set([n1,n2])==set([2,3]):
                    m, rv = determine_mrv(2, psi0)
                elif set([n1,n2])==set([2,2]):
                    m, rv = determine_mrv(1, psi0)
                else:
                    m, rv = -1, 0.0
                ms.append(m)
                rvs.append(rv)
            m = DataArray(ms, unit='au')
            rv = DataArray(rvs, unit='deg')
            if m.mean == -1 or m.std > 0.0 or rv.std > 0.0:
                if verbose:
                    print '    %s   WARNING: ' % descr +\
                          'could not determine clear trent in dihedral patterns, ' +\
                          'dihedral is ignored in force field !!!'
                deleted_diheds.append(icname)
            else:
                if verbose:
                    print '    %s   0.5*K*[1 - cos(%i(psi - %5.1f))]' % (
                        descr, m.mean, rv.mean/deg
                    )
                for i, ic in enumerate(ics):
                    ic.icf = dihed_angle
                    ic.qunit = 'deg'
                    self.pot.terms[icname][i] = CosineTerm(
                        ic, system.ref.coords, 0.0, rv.mean, m.mean
                    )
        for icname in deleted_diheds:
            #del system.ics[icname]
            del self.pot.terms[icname]

    def _get_nterms(self):
        'Method that returns the number of valence terms in the force field.'
        return len(self.pot.terms)

    nterms = property(_get_nterms)

    def update_fftable(self, fftab):
        '''
            A method to update all force field parameters (force constants and
            rest values) with the values from the given FFTable.

            **Arguments**

            fftab
                An instance of the FFTable class containing force field
                parameters.
        '''
        for icname in sorted(self.pot.terms.keys()):
            if not icname in fftab.pars.keys():
                continue
            for term in self.pot.terms[icname]:
                k, q0 = fftab[icname]
                term.k = k
                term.q0 = q0

    def get_fftable(self):
        '''
            A method to return a FFTable instance containing all force field
            parameters (force constants and rest values).
        '''
        fftab = FFTable()
        for icname in sorted(self.pot.terms.keys()):
            ks = []
            q0s = []
            ms = []
            for term in self.pot.terms[icname]:
                ks.append(term.k)
                q0s.append(term.q0)
                if isinstance(term, CosineTerm):
                    ms.append(term.A)
            if isinstance(term, CosineTerm):
                fftab.add(icname,
                    DataArray(data=ks, unit=term.ic.kunit),
                    DataArray(data=q0s, unit=term.ic.qunit),
                    m=DataArray(data=ms, unit='au')
                )
            else:
                fftab.add(icname,
                    DataArray(data=ks, unit=term.ic.kunit),
                    DataArray(data=q0s, unit=term.ic.qunit)
                )
        return fftab

    def update_fcs(self, fcs):
        '''
            A method to update the force constants of the valence terms.

            **Aruments**

            fcs
                A numpy array containing the new force constants. The ordering
                of fcs in the input argument should be the same as the ordering
                of sorted(system.ics.keys()).
        '''
        for i, icname in enumerate(sorted(self.pot.terms.keys())):
            for term in self.pot.terms[icname]:
                term.k = fcs[i]

    def get_fcs(self):
        '''
            A method to return the force constants of the valence terms. The
            ordering of fcs in the output will be the same as the ordering of
            sorted(system.ics.keys()).
        '''
        fcs = np.zeros(self.nterms, float)
        for i, icname in enumerate(sorted(self.pot.terms.keys())):
            for term in self.pot.terms[icname]:
                fcs[i] = term.k
        return fcs


#####  Potentials


class BasePot(object):
    '''
        A base class for defining potentials
    '''
    def __init__(self, kind):
        self.kind = kind

    def  calc_energy(self, coords):
        raise NotImplementedError

    def  calc_gradient(self, coords):
        raise NotImplementedError

    def  calc_hessian(self, coords):
        raise NotImplementedError


class ZeroPot(BasePot):
    '''
        A class defining a zero-valued potential to describe any part of the AI
        or FF energy.
    '''
    def __init__(self):
        BasePot.__init__(self, 'Zero')

    def calc_energy(self, coords):
        return 0.0

    def calc_gradient(self, coords):
        return np.zeros([len(coords), 3], float)

    def calc_hessian(self, coords):
        return np.zeros([len(coords), 3, len(coords), 3], float)


class HarmonicPot(BasePot):
    '''
        A class defining a harmonic potential to describe any part of the AI or
        FF energy.
    '''
    def __init__(self, kind, coords0, energy0, grad0, hess0):
        BasePot.__init__(self, '%s (Harmonic)' %kind)
        self.coords0 = coords0.copy()
        self.energy0 = energy0
        self.grad0 = grad0.copy()
        self.hess0 = hess0.copy()
        self.natoms = len(coords0)

    def calc_energy(self, coords):
        energy = self.energy0
        dx = (coords - self.coords0).reshape([3*self.natoms])
        energy += np.dot(self.grad0.reshape([3*self.natoms]), dx)
        energy += 0.5*np.dot(dx, np.dot(self.hess0.reshape([3*self.natoms, 3*self.natoms]), dx))
        return energy

    def calc_gradient(self, coords):
        dx = (coords - self.coords0).reshape([3*self.natoms])
        return self.grad0 + np.dot(self.hess0.reshape([3*self.natoms, 3*self.natoms]), dx)

    def calc_hessian(self, coords):
        return self.hess0


class CoulPointPot(BasePot):
    '''
        A class defining the Coulomb potential between point charges to describe
        the FF electrostatic energy.
    '''
    def __init__(self, charges, scales, scaled_pairs, coords0=None):
        BasePot.__init__(self, 'CoulombPoint')
        self.charges = charges
        self.scales = scales
        self.scaled_pairs = scaled_pairs
        self.shift = 0.0
        if coords0 is not None:
            self.shift = -self.calc_energy(coords0)

    def _get_scale(self, i, j):
        if [i, j] in self.scaled_pairs[0] or [j, i] in self.scaled_pairs[0]:
            return self.scales[0]
        elif [i, j] in self.scaled_pairs[1] or [j, i] in self.scaled_pairs[1]:
            return self.scales[1]
        elif [i, j] in self.scaled_pairs[2] or [j, i] in self.scaled_pairs[2]:
            return self.scales[2]
        else:
            return 1.0

    def calc_energy(self, coords):
        energy = self.shift
        for i, qi in enumerate(self.charges):
            for j, qj in enumerate(self.charges):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                bond = IC('_internal_ei_bond', [i, j], bond_length)
                energy += qi*qj/bond.value(coords)*scale
        return energy

    def calc_gradient(self, coords):
        grad = np.zeros(3*len(self.charges), float)
        for i, qi in enumerate(self.charges):
            for j, qj in enumerate(self.charges):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                bond = IC('_internal_ei_bond', [i, j], bond_length)
                r = bond.value(coords)
                grad += -qi*qj/(r**2)*bond.grad(coords)*scale
        return grad

    def calc_hessian(self, coords):
        hess = np.zeros([3*len(self.charges), 3*len(self.charges)], float)
        for i, qi in enumerate(self.charges):
            for j, qj in enumerate(self.charges):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                bond = IC('_internal_ei_bond', [i, j], bond_length)
                r = bond.value(coords)
                qgrad = bond.grad(coords)
                hess += qi*qj/(r**2)*(2.0/r*np.outer(qgrad, qgrad) - bond.hess(coords))*scale
        return hess


class CoulGaussPot(BasePot):
    '''
        A class defining the Coulomb potential between gaussian charges to describe
        the FF electrostatic energy.
    '''
    def __init__(self, charges, sigmas, scales, scaled_pairs, coords0=None):
        BasePot.__init__(self, 'CoulombGaussian')
        self.charges = charges
        self.sigmas = sigmas
        self.scales = scales
        self.scaled_pairs = scaled_pairs
        self.shift = 0.0
        if coords0 is not None:
            self.shift = -self.calc_energy(coords0)

    def _get_scale(self, i, j):
        if [i, j] in self.scaled_pairs[0] or [j, i] in self.scaled_pairs[0]:
            return self.scales[0]
        elif [i, j] in self.scaled_pairs[1] or [j, i] in self.scaled_pairs[1]:
            return self.scales[1]
        elif [i, j] in self.scaled_pairs[2] or [j, i] in self.scaled_pairs[2]:
            return self.scales[2]
        else:
            return 1.0

    def calc_energy(self, coords):
        energy = self.shift
        for i, qi in enumerate(self.charges):
            for j, qj in enumerate(self.charges):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                bond = IC('_internal_ei_bond', [i, j], bond_length)
                r = bond.value(coords)
                sigma = np.sqrt(self.sigmas[i]**2+self.sigmas[j]**2)
                energy += scale*qi*qj/r*math.erf(r/sigma)
        return energy

    def calc_gradient(self, coords):
        grad = np.zeros(3*len(self.charges), float)
        for i, qi in enumerate(self.charges):
            for j, qj in enumerate(self.charges):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                bond = IC('_internal_ei_bond', [i, j], bond_length)
                r = bond.value(coords)
                sigma = np.sqrt(self.sigmas[i]**2+self.sigmas[j]**2)
                #intermediate results
                erf = math.erf(r/sigma)
                exp = np.exp(-(r/sigma)**2)/np.sqrt(np.pi)
                #update grad
                grad += scale*qi*qj/r*(-erf/r + 2.0*exp/sigma)*bond.grad(coords)
        return grad

    def calc_hessian(self, coords):
        hess = np.zeros([3*len(self.charges), 3*len(self.charges)], float)
        for i, qi in enumerate(self.charges):
            for j, qj in enumerate(self.charges):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                bond = IC('_internal_ei_bond', [i, j], bond_length)
                r = bond.value(coords)
                qgrad = bond.grad(coords)
                sigma = np.sqrt(self.sigmas[i]**2+self.sigmas[j]**2)
                #intermediate results
                erf = math.erf(r/sigma)
                exp = np.exp(-(r/sigma)**2)/np.sqrt(np.pi)
                dVdr = (-erf/r + 2.0/sigma*exp)/r
                d2Vdr2 = (erf/r - 2*exp/sigma)/r**2 - 2*exp/sigma**3
                #update hessian
                hess += scale*qi*qj*(2*d2Vdr2*np.outer(qgrad, qgrad) + dVdr*bond.hess(coords))
        return hess


class LennardJonesPot(BasePot):
    '''
        A class defining the Lennard-Jones potential between atom pairs to
        describe the FF van der Waals energy.
    '''
    def __init__(self, sigmas, epsilons, scales, scaled_pairs, coords0=None):
        BasePot.__init__(self, 'LennartJones')
        self.sigmas = sigmas
        self.epsilons = epsilons
        self.scales = scales
        self.scaled_pairs = scaled_pairs
        self.shift = 0.0
        if coords0 is not None:
            self.shift = -self.calc_energy(coords0)

    def _get_scale(self, i, j):
        if [i, j] in self.scaled_pairs[0] or [j, i] in self.scaled_pairs[0]:
            return self.scales[0]
        elif [i, j] in self.scaled_pairs[1] or [j, i] in self.scaled_pairs[1]:
            return self.scales[1]
        elif [i, j] in self.scaled_pairs[2] or [j, i] in self.scaled_pairs[2]:
            return self.scales[2]
        else:
            return 1.0

    def calc_energy(self, coords):
        energy = self.shift
        for i, (si, ei) in enumerate(zip(self.sigmas, self.epsilons)):
            for j, (sj, ej) in enumerate(zip(self.sigmas, self.epsilons)):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                sigma = 0.5*(si+sj)
                epsilon = np.sqrt(ei*ej)
                bond = IC('_internal_vdw_bond', [i, j], bond_length)
                x = (sigma/bond.value(coords))
                energy += 4.0*epsilon*(x**12-x**6)*scale
        return energy

    def calc_gradient(self, coords):
        grad = np.zeros(3*len(coords), float)
        for i, (si, ei) in enumerate(zip(self.sigmas, self.epsilons)):
            for j, (sj, ej) in enumerate(zip(self.sigmas, self.epsilons)):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                sigma = 0.5*(si+sj)
                epsilon = np.sqrt(ei*ej)
                bond = IC('_internal_vdw_bond', [i, j], bond_length)
                x = (sigma/bond.value(coords))
                grad -= 24.0*epsilon/sigma*(2.0*x**13-x**7)*bond.grad(coords)*scale
        return grad

    def calc_hessian(self, coords):
        hess = np.zeros([3*len(coords), 3*len(coords)], float)
        for i, (si, ei) in enumerate(zip(self.sigmas, self.epsilons)):
            for j, (sj, ej) in enumerate(zip(self.sigmas, self.epsilons)):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                sigma = 0.5*(si+sj)
                epsilon = np.sqrt(ei*ej)
                bond = IC('_internal_vdw_bond', [i, j], bond_length)
                x = (sigma/bond.value(coords))
                qgrad = bond.grad(coords)
                hess += 24.0*epsilon/sigma**2*(26*x**14-7*x**8)*np.outer(qgrad, qgrad)*scale
                hess -= 24.0*epsilon/sigma*(2*x**13-x**7)*bond.hess(coords)*scale
        return hess


class MM3BuckinghamPot(BasePot):
    '''
        A class defining the MM3-Buckingham potential between atom pairs to
        describe the FF van der Waals energy.
    '''
    def __init__(self, sigmas, epsilons, scales, scaled_pairs, coords0=None):
        BasePot.__init__(self, 'MM3Buckingham')
        self.sigmas = sigmas
        self.epsilons = epsilons
        self.scales = scales
        self.scaled_pairs = scaled_pairs
        self.shift = 0.0
        if coords0 is not None:
            self.shift = -self.calc_energy(coords0)

    def _get_scale(self, i, j):
        if [i, j] in self.scaled_pairs[0] or [j, i] in self.scaled_pairs[0]:
            return self.scales[0]
        elif [i, j] in self.scaled_pairs[1] or [j, i] in self.scaled_pairs[1]:
            return self.scales[1]
        elif [i, j] in self.scaled_pairs[2] or [j, i] in self.scaled_pairs[2]:
            return self.scales[2]
        else:
            return 1.0

    def calc_energy(self, coords):
        energy = self.shift
        for i, (si, ei) in enumerate(zip(self.sigmas, self.epsilons)):
            for j, (sj, ej) in enumerate(zip(self.sigmas, self.epsilons)):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                sigma = 0.5*(si+sj)
                epsilon = np.sqrt(ei*ej)
                bond = IC('_internal_vdw_bond', [i, j], bond_length)
                x = (bond.value(coords)/sigma)
                energy += scale*epsilon*(1.84e5*np.exp(-12.0*x) - 2.25/x**6)
        return energy

    def calc_gradient(self, coords):
        grad = np.zeros(3*len(coords), float)
        for i, (si, ei) in enumerate(zip(self.sigmas, self.epsilons)):
            for j, (sj, ej) in enumerate(zip(self.sigmas, self.epsilons)):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                sigma = 0.5*(si+sj)
                epsilon = np.sqrt(ei*ej)
                bond = IC('_internal_vdw_bond', [i, j], bond_length)
                x = (bond.value(coords)/sigma)
                grad += scale*epsilon/sigma*(-2.208e6*np.exp(-12.0*x) + 13.5/x**7)*bond.grad(coords)
        return grad

    def calc_hessian(self, coords):
        hess = np.zeros([3*len(coords), 3*len(coords)], float)
        for i, (si, ei) in enumerate(zip(self.sigmas, self.epsilons)):
            for j, (sj, ej) in enumerate(zip(self.sigmas, self.epsilons)):
                if j >= i: break
                scale = self._get_scale(i, j)
                if scale==0.0: continue
                sigma = 0.5*(si+sj)
                epsilon = np.sqrt(ei*ej)
                bond = IC('_internal_vdw_bond', [i, j], bond_length)
                x = (bond.value(coords)/sigma)
                qgrad = bond.grad(coords)
                dVdr = -2.208e6*np.exp(-12.0*x) + 13.5/x**7
                d2Vdr2 = 2.6496e7*np.exp(-12.0*x)-94.5/x**8
                hess += scale*epsilon/sigma*(d2Vdr2/sigma*np.outer(qgrad, qgrad) + dVdr*bond.hess(coords))
        return hess


class NonbondedYaffPot(BasePot):
    '''
        A class defining the nonbonded potential(s) with a Yaff Forcefield
        instance.
    '''
    def __init__(self, ff):
        BasePot.__init__(self, 'NonbondedYaff')
        # Check that the valence part is not included in the force field
        names = [part.name for part in ff.parts]
        if 'valence' in names:
            raise UserWarning("You are trying to include a covalent part in the NonbondedYaff potential")
        self.ff = ff

    def calc_energy(self, coords):
        # Set the new coordinates in the Yaff system
        self.ff.system.pos[:] = coords
        # Update the neighbourlist
        self.ff.nlist.update()
        # Compute the energy using Yaff
        energy = self.ff.compute()
        return energy

    def calc_gradient(self, coords):
        natoms = len(coords)
        gradient = np.zeros([natoms, 3], float)
        # Set the new coordinates in the Yaff system
        self.ff.system.pos[:] = coords
        # Update the neighbourlist
        self.ff.nlist.update()
        # Compute the gradient using Yaff
        energy = self.ff.compute(gradient)
        return gradient.ravel()


    def calc_hessian(self, coords):
        # Set the new coordinates in the Yaff system
        self.ff.system.pos[:] = coords
        # Update the neighbourlist
        self.ff.nlist.update()
        # Compute the hessian using Yaff
        ndof = np.prod(self.ff.system.pos.shape)
        hess = np.zeros((ndof,ndof), float)
        self.ff.compute(hess=hess)
        return hess


class TermListPot(BasePot):
    '''
        A class for a potential defined as the sum of multiple terms to describe
        the FF valence energy.
    '''
    def __init__(self, terms):
        BasePot.__init__(self, 'TermList')
        self.terms = terms

    def calc_energy(self, coords):
        energy = 0.0
        for icname, terms in sorted(self.terms.iteritems()):
            for term in terms:
                energy += term.calc_energy(coords=coords)
        return energy

    def calc_gradient(self, coords):
        natoms = len(coords)
        gradient = np.zeros([natoms, 3], float)
        for icname, terms in sorted(self.terms.iteritems()):
            for term in terms:
                gradient += term.calc_gradient(coords=coords)
        return gradient

    def calc_hessian(self, coords):
        natoms = len(coords)
        hessian = np.zeros([natoms, 3, natoms, 3], float)
        for icname, terms in sorted(self.terms.iteritems()):
            for term in terms:
                hessian += term.calc_hessian(coords=coords)
        return hessian