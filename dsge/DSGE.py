import sympy
import yaml
from .symbols import Variable, Equation, Shock, Parameter, TSymbol

import scipy.stats as stats
from sympy.matrices import Matrix, zeros
import re
import numpy as np
import itertools
import pandas as p
from .StateSpaceModel import LinearDSGEModel

import warnings


class EquationList(list):
    """A container for holding an set of equations."""

    def __init__(self, args, context={}):
        self.context = context
        return super(EquationList, self).__init__(args)

    def __setitem__(self, key, value):

        if isinstance(value, str):
            lhs, rhs = value.split('=')

            lhs = eval(lhs, self.context)
            rhs = eval(rhs, self.context)

            value = Equation(lhs, rhs)

        return super(EquationList, self).__setitem__(key, value)


def read_data_file(datafile, obs_names):
    
    if type(datafile)==dict:
        startdate = datafile['start']
        datafile = datafile['file']
    else:
        startdate = 0

    try:
        with open(datafile, 'r') as df:
            data = df.read()
            delim_dict = {}

            if data.find(',') > 0:
                delim_dict['delimiter'] = ','

            data = np.genfromtxt(datafile, missing_values='NaN', **delim_dict)
    except:
        warnings.warn("%s could not be opened." % datafile)
        data = np.nan * np.ones((100, len(obs_names)))
        startdate = 0

    if len(obs_names) > 1:
        data = p.DataFrame(data[:, :len(obs_names)], columns=list(map(lambda x: str(x), obs_names)))
    else:
        data = p.DataFrame(data, columns=list(map(lambda x: str(x), obs_names)))

    if startdate is not 0:
        nobs = data.shape[0]
        data.index = p.period_range(startdate, freq='Q', periods=nobs)

    return data

def construct_prior(prior_list, parameters):

    prior_type = ['beta', 'gamma', 'normal', 'inv_gamma', 'uniform', 'fixed']
    prior = []
    for par in parameters:
        prior_spec = prior_list[par.name]

        ptype = prior_spec[0]
        pmean = prior_spec[1]
        pstdd = prior_spec[2]
        from scipy.stats import beta, norm, uniform, gamma
        from dsge.OtherPriors import InvGamma
        if ptype=='beta':
            a = (1-pmean)*pmean**2/pstdd**2 - pmean
            b = a*(1/pmean - 1)
            pr = beta(a, b)
            pr.name = 'beta'
            prior.append(pr)
        if ptype=='gamma':
            b = pstdd**2/pmean
            a = pmean/b
            pr = gamma(a, scale=b)
            pr.name = 'gamma'
            prior.append(pr)
        if ptype=='normal':
            a = pmean
            b = pstdd
            pr = norm(loc=a, scale=b)
            pr.name='norm'
            prior.append(pr)
        if ptype=='inv_gamma':
            a = pmean
            b = pstdd
            prior.append(InvGamma(a, b))
        if ptype=='uniform':
            a, b = pmean, pstdd
            pr = uniform(loc=a, scale=(b-a))
            pr.name = 'uniform'
            prior.append(pr)

    return prior



class DSGE(dict):

    max_lead = 1;
    max_lag  = 1;

    def __init__(self, *kargs, **kwargs):
        super(DSGE, self).__init__(self, *kargs, **kwargs)

        fvars = []
        lvars = []

        # get forward looking variables
        for eq in self['equations']:

            variable_too_far = [v for v in eq.atoms() if isinstance(v, Variable) and v.date > 1]
            variable_too_early = [v for v in eq.atoms() if isinstance(v, Variable) and v.date < -1]

            eq_fvars = [v for v in eq.atoms() if isinstance(v, TSymbol) and v.date > 0]
            eq_lvars = [v for v in eq.atoms() if isinstance(v, TSymbol) and v.date < 0]

            fvars = list(set(fvars).union(eq_fvars))
            lvars = list(set(lvars).union(set(eq_lvars)))

        self['info']['nstate'] = len(self.variables) + len(fvars)

        self['fvars'] = fvars
        self['fvars_lagged'] = [Parameter('__LAGGED_'+f.name) for f in fvars]
        self['lvars'] = lvars
        self['re_errors'] = [Shock('eta_'+v.name) for v in self['fvars']]

        self['re_errors_eq'] = []
        i = 0
        for fv, lag_fv in zip(fvars, self['fvars_lagged']):
            self['re_errors_eq'].append(Equation(fv(-1) - lag_fv -  self['re_errors'][i], 0))
            i += 1

        if 'make_log' in self.keys():
            self['perturb_eq'] = []
            sub_dict = dict()
            sub_dict.update({v:Parameter(v.name+'ss')*sympy.exp(v) for v in self['make_log']})
            sub_dict.update({v(-1):Parameter(v.name+'ss')*sympy.exp(v(-1)) for v in self['make_log']})
            sub_dict.update({v(1):Parameter(v.name+'ss')*sympy.exp(v(1)) for v in self['make_log']})

            for eq in self.equations:
                peq = eq.subs(sub_dict)
                self['perturb_eq'].append(peq)

            self['ss_ordering'] = [Variable(v.name+'ss') for v in self['make_log']]


        else:
            self['perturb_eq'] = self['equations']

        # context = [(s.name, s) for s in self['par_ordering']+self['var_ordering']+self['shk_ordering']+self['para_func']]
        # context = dict(context)
        # context['log'] = sympy.log
        # context['exp'] = sympy.exp
        context = {}
        #self['pertub_eq'] = EquationList(self['perturb_eq'], context)


        return

    def __repr__(self):
        return "A DSGE Model."

    @property
    def equations(self):
        return self['equations']

    @property
    def variables(self):
        return self['var_ordering']

    @property
    def parameters(self):
        return self['par_ordering']

    @property
    def shocks(self):
        return self['shk_ordering']

    @property
    def name(self):
        return self['name']

    @property
    def neq(self):
        return len(self['perturb_eq'])

    @property
    def neq_fort(self):
        return self.neq+self.neta

    @property
    def neta(self):
        return len(self['fvars'])

    @property
    def ns(self):
        return

    @property
    def ny(self):
        return len(self['observables'])

    @property
    def neps(self):
        return len(self['shk_ordering'])

    @property
    def npara(self):
        return len(self.parameters)

    def p0(self):
        return list(map(lambda x: self['calibration'][str(x)], self.parameters))

    def calibrate(**kwargs):
        pass
        
    def python_sims_matrices(self, matrix_format='numeric'):


        from sympy.utilities.lambdify import lambdify
        vlist = self['var_ordering'] + self['fvars']
        llist = [l(-1) for l in self['var_ordering']] + self['fvars_lagged']
        slist = self['shk_ordering']

        subs_dict = dict()

        eq_cond = self['perturb_eq'] + self['re_errors_eq']

        sub_var = self['var_ordering']
        subs_dict.update( {v:0 for v in sub_var})
        subs_dict.update( {v(1):0 for v in sub_var})
        subs_dict.update( {v(-1):0 for v in sub_var})


        svar = len(vlist)
        evar = len(slist)
        rvar = len(self['re_errors'])
        ovar = len(self['observables'])

        GAM0 = zeros(svar, svar)
        GAM1 = zeros(svar, svar)
        PSI  = zeros(svar, evar)
        PPI  = zeros(svar, rvar)

        eq_i = 0
        for eq in eq_cond:
            curr_var = filter(lambda x: x.date >= 0, eq.atoms(Variable))

            for v in curr_var:
                v_j = vlist.index(v)
                GAM0[eq_i, v_j] = -(eq).set_eq_zero.diff(v).subs(subs_dict)

            past_var = filter(lambda x: x in llist, eq.atoms())

            for v in past_var:
                v_j = llist.index(v)
                GAM1[eq_i, v_j] = eq.set_eq_zero.diff(v).subs(subs_dict)

            shocks = filter(lambda x: x, eq.atoms(Shock))

            for s in shocks:
                if s not in self['re_errors']:
                    s_j = slist.index(s)
                    PSI[eq_i, s_j] = eq.set_eq_zero.diff(s).subs(subs_dict)
                else:
                    s_j = self['re_errors'].index(s)
                    PPI[eq_i, s_j] = eq.set_eq_zero.diff(s).subs(subs_dict)

            eq_i += 1
            #print "\r Differentiating equation {0} of {1}.".format(eq_i, len(eq_cond)),
        DD = zeros(ovar, 1)
        ZZ = zeros(ovar, svar)

        eq_i = 0
        for obs in self['observables']:
            eq = self['obs_equations'][str(obs)]

            DD[eq_i, 0] = eq.subs(subs_dict)

            curr_var = filter(lambda x: x.date >= 0, eq.atoms(Variable))
            for v in curr_var:
                v_j = vlist.index(v)
                ZZ[eq_i, v_j] = eq.diff(v).subs(subs_dict)

            eq_i += 1


        if matrix_format=='symbolic':
            QQ = self['covariance']
            HH = self['measurement_errors']
            return GAM0, GAM1, PSI, PPI, QQ, DD, ZZ, HH
        #print ""
        from collections import OrderedDict
        subs_dict = []
        context = dict([(p.name, p) for p in self.parameters])
        context['exp'] = sympy.exp
        context['log'] = sympy.log
        context_f = {}
        context_f['exp'] = np.exp
        if 'helper_func' in self['__data__']['declarations']:
            from imp import load_source
            f = self['__data__']['declarations']['helper_func']['file']
            module = load_source('helper_func', f)
            for n in self['__data__']['declarations']['helper_func']['names']:
                context[n] = sympy.Function(n) #getattr(module, n)
                context_f[n] = getattr(module, n)
        #import sys
        #sys.stdout.flush()
        ss = {}

        for p in self['other_para']:
            ss[str(p)] = eval(str(self['para_func'][p.name]), context)
            context[str(p)] = ss[str(p)]
            #print("\r Constructing substitution dictionary [{0:20s}]".format(p.name),)
        #sys.stdout.flush()
        #print ""
        #context_f['numpy'] = 'numpy'
        GAM0 = lambdify([self.parameters+self['other_para']], GAM0)#, modules={'ImmutableDenseMatrix': np.array})#'numpy')
        GAM1 = lambdify([self.parameters+self['other_para']], GAM1)#, modules={'ImmutableDenseMatrix': np.array})#'numpy')
        PSI = lambdify([self.parameters+self['other_para']], PSI)#, modules={'ImmutableDenseMatrix': np.array})#'numpy')
        PPI = lambdify([self.parameters+self['other_para']], PPI)#, modules={'ImmutableDenseMatrix': np.array})#'numpy')

        psi = lambdify([self.parameters], [ss[str(px)] for px in self['other_para']])#, modules=context_f)

        def add_para_func(f):
            def wrapped_f(px):
                return f([*px, *psi(px)])
            return wrapped_f

        self.GAM0 = add_para_func(GAM0)
        self.GAM1 = add_para_func(GAM1)
        self.PSI = add_para_func(PSI)
        self.PPI = add_para_func(PPI)

        QQ = self['covariance'].subs(subs_dict)
        HH = self['measurement_errors'].subs(subs_dict)

        DD = DD.subs(subs_dict)
        ZZ = ZZ.subs(subs_dict)

        QQ = lambdify([self.parameters+self['other_para']], self['covariance'])
        HH = lambdify([self.parameters+self['other_para']], self['measurement_errors'])
        DD = lambdify([self.parameters+self['other_para']], DD)
        ZZ = lambdify([self.parameters+self['other_para']], ZZ)

        self.QQ = add_para_func(QQ)
        self.DD = add_para_func(DD)
        self.ZZ = add_para_func(ZZ)
        self.HH = add_para_func(HH)

        return GAM0, GAM1, PSI, PPI

    def compile_model(self):
        self.python_sims_matrices()

        GAM0 = self.GAM0
        GAM1 = self.GAM1
        PSI = self.PSI
        PPI = self.PPI

        QQ = self.QQ
        DD = self.DD
        ZZ = self.ZZ
        HH = self.HH


        if 'observables' not in self:
            self['observables'] = self['variables'].copy()
            self['obs_equations'] = dict(self['observables'], self['observables'])

        if 'data' in self['__data__']['estimation']:
            data = read_data_file(self['__data__']['estimation']['data'], self['observables'])
        else:
            data = np.nan * np.ones((100, len(self['observables'])))
            
        prior = None
        if 'prior' in self['__data__']['estimation']:
            prior = construct_prior(self['__data__']['estimation']['prior'], self.parameters)

        from .Prior import Prior as pri
        dsge = LinearDSGEModel(data, GAM0, GAM1, PSI, PPI,
                               QQ, DD, ZZ, HH, t0=0,
                               shock_names=list(map(str, self.shocks)),
                               state_names=list(map(str, self.variables+self['fvars'])),
                               obs_names=list(map(str, self['observables'])),
                               prior=pri(prior))

        return dsge

    def solve_model(self, p0):

        #if self.GAM0 == None:
        self.python_sims_matrices()

        from gensys import gensys_wrapper as gensys

        G0 = self.GAM0(*p0)
        G1 = self.GAM1(*p0)
        PSI = self.PSI(*p0)
        PPI = self.PPI(*p0)
        C0 = np.zeros((G0.shape[0]))
        TT, CC, RR, fmat, fwt, ywt, gev, RC, loose = gensys.call_gensys(G0, G1, C0, PSI, PPI, 1.00000000001)

        return TT, RR, RC


    @classmethod
    def read(cls, mfile):
        """

        """

        f = open(mfile)
        txt = f.read()
        f.close()


        txt = txt.replace('^', '**')
        txt = txt.replace(';', '')
        txt = re.sub(r"@ ?\n", " ", txt)
        model_yaml = yaml.load(txt)

        dec = model_yaml['declarations']
        cal = model_yaml['calibration']

        name = dec['name']

        var_ordering = [Variable(v) for v in dec['variables']]
        par_ordering = [Parameter(v) for v in dec['parameters']]
        shk_ordering = [Shock(v) for v in dec['shocks']]


        if 'para_func' in dec:
            other_para   = [Parameter(v) for v in dec['para_func']]
        else:
            other_para = []

        if 'observables' in dec:
            observables = [Variable(v) for v in dec['observables']]
            obs_equations = model_yaml['equations']['observables']
        else:
            observables = []
            obs_equations = dict()

        if 'measurement_errors' in dec:
            measurement_errors = [Shock(v) for v in dec['measurement_errors']]
        else:
            measurement_errors = None


        if 'make_log' in dec:
            make_log = [Variable(v) for v in dec['make_log']]
        else:
            make_log = []

        steady_state = [0]
        init_values = [0]

        context = [(s.name,s) for s in var_ordering + par_ordering + shk_ordering + other_para]
        context = dict(context)

        for f in [sympy.log, sympy.exp,
                  sympy.sin, sympy.cos, sympy.tan,
                  sympy.asin, sympy.acos, sympy.atan,
                  sympy.sinh, sympy.cosh, sympy.tanh,
                  sympy.pi, sympy.sign]:
            context[str(f)] = f

        context['sqrt'] = sympy.sqrt
        context['__builtins__'] = None

        equations = []

        if 'model' in model_yaml['equations']:
            raw_equations = model_yaml['equations']['model']
        else:
            raw_equations = model_yaml['equations']


        for eq in raw_equations:
            if '=' in eq:
                lhs, rhs = str.split(eq, '=')
            else:
                lhs, rhs = eq, '0'

            try:
                lhs = eval(lhs, context)
                rhs = eval(rhs, context)
            except TypeError as e:
                print('While parsing %s, got this error: %s' % (eq, repr(e)))
                return

            equations.append(Equation(lhs, rhs))



        #------------------------------------------------------------
        # Figure out max leads and lags
        #------------------------------------------------------------
        it = itertools.chain.from_iterable

        max_lead_exo = dict.fromkeys(shk_ordering)
        max_lag_exo = dict.fromkeys(shk_ordering)

        all_shocks = [list(eq.atoms(Shock)) for eq in equations]

        for s in shk_ordering:
            max_lead_exo[s] = max([i.date for i in it(all_shocks) if i.name == s.name])
            max_lag_exo[s] = min([i.date for i in it(all_shocks) if i.name == s.name])


        # arbitrary lags of exogenous shocks
        for s in shk_ordering:
            if abs(max_lag_exo[s]) > 0:
                var_s = Variable(s.name+"_VAR")
                var_ordering.append(var_s)
                equations.append(Equation(var_s, s))

                subs1 = [s(-i) for i in np.arange(1, abs(max_lag_exo[s])+1)]
                subs2 = [var_s(-i) for i in np.arange(1, abs(max_lag_exo[s])+1)]
                subs_dict = dict(zip(subs1, subs2))
                equations = [eq.subs(subs_dict) for eq in equations]


        all_vars = [list(eq.atoms(Variable)) for eq in equations]
        max_lead_endo = dict.fromkeys(var_ordering)
        max_lag_endo = dict.fromkeys(var_ordering)

        for v in var_ordering:
            max_lead_endo[v] = max([i.date for i in it(all_vars) if i.name == v.name])
            max_lag_endo[v] = min([i.date for i in it(all_vars) if i.name == v.name])

        #------------------------------------------------------------
        # arbitrary lags/leads of exogenous shocks
        subs_dict = dict()
        old_var = var_ordering[:]
        for v in old_var:

            # lags
            for i in np.arange(2, abs(max_lag_endo[v])+1):
                # for lag l need to add l-1 variable
                var_l = Variable(v.name + "_LAG" + str(i-1))

                if i == 2:
                    var_l_1 = Variable(v.name, date=-1)
                else:
                    var_l_1 = Variable(v.name + "_LAG" + str(i-2), date=-1)

                subs_dict[Variable(v.name, date=-i)] = var_l(-1)
                var_ordering.append(var_l)
                equations.append(Equation(var_l, var_l_1))


            # still need to do leads

        equations = [eq.subs(subs_dict) for eq in equations]

        cov = cal['covariances']

        nshock = len(shk_ordering)
        npara  = len(par_ordering)

        info = {'nshock': nshock, 'npara': npara}
        QQ = sympy.zeros(nshock, nshock)
        for key, value in cov.items():
            shocks = key.split(",")

            if len(shocks)==1:
                shocks.append(shocks[0])

            if len(shocks)==2:
                shocki = Shock(shocks[0].strip())
                shockj = Shock(shocks[1].strip())

                indi = shk_ordering.index(shocki)
                indj = shk_ordering.index(shockj)

                QQ[indi, indj] = eval(str(value), context)
                QQ[indj, indi] = QQ[indi, indj]

            else:
                "fdfadsf"

        nobs = len(obs_equations)
        HH = sympy.zeros(nobs, nobs)

        if measurement_errors is not None:
            for key, value in cal['measurement_errors'].items():
                shocks = key.split(",")

                if len(shocks)==1:
                    shocks.append(shocks[0])

                if len(shocks)==2:
                    shocki = Shock(shocks[0].strip())
                    shockj = Shock(shocks[1].strip())

                    indi = measurement_errors.index(shocki)
                    indj = measurement_errors.index(shockj)

                    HH[indi, indj] = eval(value, context)
                    HH[indj, indi] = HH[indi, indj]




        context['sum'] = np.sum
        context['range'] = range
        for obs in obs_equations.items():
            obs_equations[obs[0]] = eval(obs[1], context)

            

        calibration = model_yaml['calibration']['parameters']

        if 'parafunc' not in cal:
            cal['parafunc'] = {}

        model_dict = {
            'var_ordering': var_ordering,
            'par_ordering': par_ordering,
            'shk_ordering': shk_ordering,
            'other_parameters': other_para,
            'other_para': other_para,
            'para_func': cal['parafunc'],
            'calibration': calibration,
            'steady_state': steady_state,
            'init_values': init_values,
            'equations': equations,
            'covariance': QQ,
            'measurement_errors': HH,
            'meas_ordering': measurement_errors,
            'info': info,
            'make_log': make_log,
            '__data__': model_yaml,
            'name': dec['name'],
            'observables': observables,
            'obs_equations': obs_equations
            }

        model = cls(**model_dict)
        return model


