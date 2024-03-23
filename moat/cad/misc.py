import cadquery as cq

__all__ = ["slider"]


def slider(x,y,size=2, inset=0):
    """
    Returns a workspace with a slide-in guide, centered on the origin.
    
    Set "inset" to whatever tolerance you need for the subtractive part.
    """
    # sliders
    def hook(ws,offset,length):
        d=-1 if offset>0 else 1
        ws = (ws
            .moveTo(offset,0)
            .line(0,size*4+inset)
            .line(d*(size*2+inset),-size*2-inset)
            .line(-d*size,-size)
            .line(0,-size)
            .close()
            .extrude(length)
            )
        return ws

    h1 = hook(cq.Workplane("XZ"),x,-y)
    h2 = hook(cq.Workplane("XZ"),0,-y)
    h3 = hook(cq.Workplane("YZ"),y,x)
    return h1.union(h2, clean=False).union(h3, clean=True).translate((-x/2,-y/2,0))

