import numpy as np

from numba import jit


@jit(nopython=True)
def chand_recursion(y, TT, RR, QQ, DD, ZZ, HH, P0,t0=0):
    nobs, ny = y.shape
    ns = TT.shape[0]

    Pt = P0

    loglh = 0.0
    At = np.zeros(shape=(ns))


    Ft = ZZ @ Pt @ ZZ.T + HH
    Ft = 0.5 * (Ft + Ft.T)
    iFt = np.linalg.inv(Ft)

    St = TT @ Pt @ ZZ.T
    Mt = -iFt
    Kt = St @ iFt

    for i in range(nobs):
        yhat = ZZ @ At + DD.flatten()
        nut = y[i] - yhat

        dFt = np.log(np.linalg.det(Ft))
        iFtnut = np.linalg.solve(Ft, nut)

        if i >= t0:
            loglh = loglh - 0.5*ny*np.log(2*np.pi) - 0.5*dFt - 0.5*np.dot(nut, iFtnut)

        At = TT@At + Kt @ nut.T
        
        ZZSt = ZZ@St;
        MSpZp = Mt@(ZZSt.T);
        TTSt = TT@St;

        Ft1  = Ft + ZZSt@MSpZp;         # F_{t+1}
        Ft1  = 0.5*(Ft1+Ft1.T);           
        iFt1 = np.linalg.inv(Ft1);
        
        Kt = (Kt@Ft + TTSt@MSpZp)@iFt1; # K_{t+1}
        St = TTSt - Kt@ZZSt;            # S_{t+1}
        Mt = Mt + MSpZp@iFt@MSpZp.T;     # M_{t+1}
        Mt = 0.5*(Mt + Mt.T);
        Ft = Ft1;
        iFt = iFt1;

    return loglh


@jit(nopython=True)
def kalman_filter(y, TT, RR, QQ, DD, ZZ, HH, P0,t0=0):

    #y = np.asarray(y)
    nobs, ny = y.shape
    ns = TT.shape[0]

    RQR = np.dot(np.dot(RR, QQ), RR.T)
    Pt = P0

    loglh = 0.0
    AA = np.zeros(shape=(ns))
    for i in range(nobs):

        not_missing = ~np.isnan(y[i])
        nact = not_missing.sum()
        yhat = ZZ[not_missing,:] @ AA + DD.flatten()[not_missing]

        nut = y[i][not_missing] - yhat

        Ft = ZZ[not_missing,:] @ Pt @ ZZ[not_missing,:].T + HH[not_missing,:][:,not_missing]
        Ft = 0.5 * (Ft + Ft.T)

        dFt = np.log(np.linalg.det(Ft))
        iFtnut = np.linalg.solve(Ft, nut)

        if i >= t0:
            loglh = loglh - 0.5*nact*np.log(2*np.pi) - 0.5*dFt - 0.5*np.dot(nut, iFtnut)
 
        TTPt = TT @ Pt
        Kt = TTPt @ ZZ[not_missing,:].T

        AA = TT @ AA + Kt @ iFtnut
        Pt = TTPt @ TT.T - Kt @ np.linalg.solve(Ft, Kt.T) + RQR

    return loglh



@jit(nopython=True)
def filter_and_smooth(y, TT, RR, QQ, DD, ZZ, HH, P0,t0=0):
    #y = np.atleast_2d(y)
    #DD = np.atleast_1d(DD)

    nobs, ny = y.shape
    ns = TT.shape[0]

    RQR = np.dot(np.dot(RR, QQ), RR.T)
    Pt = P0
    At = np.zeros(shape=(ns))

    loglh = 0.0

    forecast_means = np.zeros((nobs, ns))
    forecast_stds = np.zeros((nobs, ns))
    forecast_cov = np.zeros((nobs, ns, ns))

    filtered_means = np.zeros((nobs, ns))
    filtered_stds = np.zeros((nobs, ns))
    filtered_cov = np.zeros((nobs, ns, ns))

    smoothed_means = np.zeros((nobs, ns))
    smoothed_stds = np.zeros((nobs, ns))
    smoothed_cov = np.zeros((nobs, ns, ns))

    liks = np.zeros(nobs)

    for i in range(nobs):

        observed = ~np.isnan(y[i])
        nact = np.sum(observed)

        forecast_means[i] = At
        forecast_stds[i] = np.sqrt(np.diag(Pt))
        forecast_cov[i] = 0.5*(Pt + Pt.T)

        if nact > 0:

            yhat = (ZZ @ At)[observed] + DD[observed].flatten()
            nut = y[i][observed] - yhat 

            Ft = (ZZ @ Pt @ ZZ.T + HH)[observed, :][:, observed]
            Ft = 0.5 * (Ft + Ft.T)

            dFt = np.log(np.linalg.det(Ft))
            iFtnut = np.linalg.solve(Ft, nut)

            if i >= t0:
                liks[i] = - 0.5*nact*np.log(2*np.pi) - 0.5*dFt - 0.5*np.dot(nut, iFtnut)

            Kt = Pt @ ZZ[observed, :].T

            At1 = At + Kt @ iFtnut
            Pt1 = Pt - Kt @ np.linalg.solve(Ft, Kt.T)

        else:

            At1 = At
            Pt1 = Pt

        filtered_means[i] = At1
        filtered_stds[i] = np.sqrt(np.diag(Pt1))
        filtered_cov[i] = 0.5*Pt1 

        # forecast 
        At = TT @ At1
        Pt = TT @ Pt1 @ TT.T + RQR


    # smoother
    smoothed_means[-1] = filtered_means[-1]
    smoothed_stds[-1] = filtered_stds[-1]
    smoothed_cov[-1] = filtered_cov[-1]
   
    for i in range(nobs-2,-1,-1):
        invPt1 = np.linalg.pinv(forecast_cov[i+1])
        J = filtered_cov[i] @ TT.T @ invPt1
   
        smoothed_means[i] = filtered_means[i] + (
            J @ (smoothed_means[i+1] - forecast_means[i+1]) )

        PtT = filtered_cov[i] + J @ (smoothed_cov[i+1] - forecast_cov[i+1]) @ J.T
        PtT = 0.5*(PtT.T + PtT)
        smoothed_stds[i] = np.sqrt(np.diag(PtT))
        smoothed_cov[i] = PtT


    return (liks, filtered_means, filtered_stds, filtered_cov,
            forecast_means, forecast_stds, forecast_cov,
            smoothed_means, smoothed_stds, smoothed_cov)
